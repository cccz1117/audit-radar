# -*- coding: utf-8 -*-
"""多源共振检测：本地关键词聚类 + 可选 LLM 精评。"""
import json
import re
from typing import Dict, List

import requests

import config
from core.skill_loader import load_skill_prompt


class ResonanceDetector:
    """事件聚类 + 共振评分。"""

    # 高权重信源，本地评分时额外加分
    HIGH_WEIGHT_SOURCES = {"Risk.net", "Finextra", "DataCenterDynamics", "nvd-high", "nvd-critical"}

    def detect(self, candidates: List[Dict]) -> List[Dict]:
        """输入粗筛后的候选，输出聚类后的事件簇（含共振分）。"""
        clusters = self._cluster(candidates)
        for cluster in clusters:
            if config.RESONANCE_USE_AI and len(cluster.get("sources", [])) >= 2:
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
            clusters.append({
                "event_title": c["title"],
                "items": group,
                "sources": list({x["source"] for x in group}),
                "categories": list({x["category"] for x in group}),
            })
        return clusters

    @staticmethod
    def _extract_keywords(title: str) -> set:
        """提取关键词（英文、中文、数字混合）。"""
        title = title.lower()
        # 保留 2+ 字符的词
        words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", title)
        return set(words)

    def _calc_score(self, cluster: Dict) -> int:
        """本地规则计算共振分。"""
        sources = cluster.get("sources", [])
        n = len(sources)
        base = n * 10
        bonus = sum(5 for s in sources if s in self.HIGH_WEIGHT_SOURCES)
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
        """调用 cross-source-resonance skill 对多源 cluster 做精评。"""
        if not config.DASHSCOPE_API_KEY:
            cluster["resonance_score"] = self._calc_score(cluster)
            cluster["level"] = self._level(cluster["resonance_score"])
            cluster["consistency_check"] = "skipped"
            cluster["consistency_note"] = "DASHSCOPE_API_KEY not set, fallback to local score"
            return

        system_prompt = load_skill_prompt("cross-source-resonance")
        user_prompt = self._format_cluster_for_llm(cluster)

        try:
            raw = self._call_llm(system_prompt, user_prompt)
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

    def _call_llm(self, system_prompt: str, user_prompt: str) -> str:
        """调用百炼 API。"""
        headers = {
            "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.0,
            "max_tokens": 1024,
        }
        r = requests.post(
            f"{config.DASHSCOPE_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

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
