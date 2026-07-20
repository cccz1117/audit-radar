# -*- coding: utf-8 -*-
"""多源共振检测：本地关键词聚类 + 可选 LLM 精评。"""
import json
import re
from typing import Dict, List

import config
from core.llm_client import chat_completion
from core.skill_loader import load_skill_prompt

# jieba 用于中文关键词提取；缺失时回退到整段中文 token（旧行为），不影响运行
try:
    import jieba
    import jieba.analyse
    from pathlib import Path

    # 加载领域用户词典（半导体/AI/银行/监管/信安/银行 IT 实体），文件缺失则跳过
    _user_dict = Path(__file__).resolve().parent.parent / "domain_dict.txt"
    if _user_dict.exists():
        jieba.load_userdict(str(_user_dict))
    _JIEBA_OK = True
except ImportError:
    _JIEBA_OK = False


class ResonanceDetector:
    """事件聚类 + 共振评分。"""

    # 高权重阈值：信源 weight ≥ 8 时，本地共振评分额外加分
    HIGH_WEIGHT_THRESHOLD = 8
    HIGH_WEIGHT_BONUS = 5

    # 中文新闻标题模板词，聚类时从关键词中剔除（防"华为发布X/苹果发布X"式误聚）
    ZH_STOPWORDS = {
        "发布", "推出", "宣布", "全新", "最新", "新一代",
        "正式", "上线", "独家", "曝光", "回应", "产品",
    }

    def detect(self, candidates: List[Dict]) -> List[Dict]:
        """输入粗筛后的候选，输出聚类后的事件簇（含共振分）。"""
        clusters = self._cluster(candidates)
        for cluster in clusters:
            if getattr(config, "RESONANCE_USE_AI", False) and len(cluster.get("sources", [])) >= 2:
                # 多源 cluster 用 LLM 做一致性校验和精评
                self._llm_score_cluster(cluster)
            else:
                # 单源或 AI 未启用，用本地规则打分
                cluster["resonance_score"] = self._calc_score(cluster)
                cluster["level"] = self._level(cluster["resonance_score"])
                cluster["consistency_check"] = "local"
                cluster["consistency_note"] = "local keyword clustering"
        # 按共振分排序
        clusters.sort(key=lambda x: x.get("resonance_score", 0), reverse=True)
        return clusters

    def _cluster(self, candidates: List[Dict]) -> List[Dict]:
        """基于关键词聚类。"""
        clusters = []
        used = set()
        for i, c in enumerate(candidates):
            if i in used:
                continue
            group = [c]
            used.add(i)
            kw_i = self._extract_keywords(c["title"])
            for j in range(i + 1, len(candidates)):
                if j in used:
                    continue
                kw_j = self._extract_keywords(candidates[j]["title"])
                if len(kw_i & kw_j) >= 2:
                    group.append(candidates[j])
                    used.add(j)
            # 事件代表标题取簇内 weight 最高源的条目，避免随机首条标题质量不稳
            rep = max(group, key=lambda x: int(x.get("weight", 5) or 5))
            clusters.append({
                "event_title": rep["title"],
                "items": group,
                "sources": list({x["source"] for x in group}),
                "categories": list({x["category"] for x in group}),
            })
        return clusters

    @staticmethod
    def _extract_keywords(title: str) -> set:
        """提取关键词：英文/数字按单词切，中文用 jieba TF-IDF 关键词。

        extract_tags 自带 IDF 降权，公司名/产品名/漏洞编号等实体词优先，
        "发布/最新"等模板词被自然过滤；jieba 缺失时回退旧行为。
        """
        title = title.lower()
        words = set(re.findall(r"[a-z0-9]+", title))
        if _JIEBA_OK:
            zh = jieba.analyse.extract_tags(title, topK=10)
            words |= {
                w for w in zh
                if len(w) >= 2 and not w.isascii() and w not in ResonanceDetector.ZH_STOPWORDS
            }
        else:
            words |= set(re.findall(r"[\u4e00-\u9fff]{2,}", title))
        return words

    def _calc_score(self, cluster: Dict) -> int:
        """本地规则计算共振分：独立信源数 × 10 + 高权重源（weight≥阈值）加分。

        权重取自 sources.json 中每个信源的 weight 字段（随 item 携带），
        同一信源有多条 item 时取其最高 weight。
        """
        sources = cluster.get("sources", [])
        n = len(sources)
        base = n * 10
        source_weights: Dict[str, int] = {}
        for item in cluster.get("items", []):
            s = item.get("source", "")
            w = int(item.get("weight", 5) or 5)
            source_weights[s] = max(source_weights.get(s, 0), w)
        bonus = sum(
            self.HIGH_WEIGHT_BONUS
            for w in source_weights.values()
            if w >= self.HIGH_WEIGHT_THRESHOLD
        )
        return base + bonus

    @staticmethod
    def _level(score: int) -> str:
        if score >= 40:
            return "high"
        if score >= 20:
            return "medium"
        if score >= 10:
            return "low"
        return "none"

    def _llm_score_cluster(self, cluster: Dict) -> None:
        """调用 cross-source-resonance skill 对多源 cluster 做精评。

        统一走 chat_completion（task="resonance"），默认路由到 DeepSeek deepseek-v4-pro；
        可用 MODEL_RESONANCE 环境变量覆盖（如 "moonshot:kimi-k2-6"）。
        LLM 不可用或输出异常时，自动回退本地规则打分。
        """
        system_prompt = load_skill_prompt("cross-source-resonance")
        user_prompt = self._format_cluster_for_llm(cluster)

        try:
            raw = chat_completion(
                system=system_prompt,
                user=user_prompt,
                task="resonance",
                temperature=0.0,
                max_tokens=1024,
                timeout=60,
            )
            scored = self._parse_llm_output(raw)
        except Exception as e:
            if config.DEBUG:
                print(f"  [DEBUG] LLM resonance failed: {e}")
            scored = {}

        if scored and "resonance_score" in scored:
            cluster["resonance_score"] = int(scored.get("resonance_score", 0))
            cluster["level"] = scored.get("level") or self._level(cluster["resonance_score"])
            cluster["consistency_check"] = scored.get("consistency_check", "unknown")
            cluster["consistency_note"] = scored.get("consistency_note", "")
        else:
            # LLM 输出异常，回退本地打分
            cluster["resonance_score"] = self._calc_score(cluster)
            cluster["level"] = self._level(cluster["resonance_score"])
            cluster["consistency_check"] = "fallback"
            cluster["consistency_note"] = "LLM parse failed, fallback to local score"

    @staticmethod
    def _format_cluster_for_llm(cluster: Dict) -> str:
        """把 cluster 格式化成 LLM 可读的文本。"""
        lines = [
            f"事件标题：{cluster.get('event_title', '')}",
            f"涉及类别：{', '.join(cluster.get('categories', []))}",
            "",
            "相关报道：",
        ]
        for i, item in enumerate(cluster.get("items", []), 1):
            lines.append(f"[{i}] 来源：{item.get('source', '')}")
            lines.append(f"    标题：{item.get('title', '')}")
            lines.append(f"    日期：{item.get('date', '')[:10]}")
            lines.append(f"    摘要：{item.get('summary', '')[:300]}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    def _parse_llm_output(raw: str) -> Dict:
        """解析 LLM 返回的 JSON。兼容 markdown 代码块。"""
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        # 有些模型会在 JSON 外加说明文字，尝试提取 {} 包裹的内容
        if not text.startswith("{"):
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                text = match.group(0)
        return json.loads(text)
