# -*- coding: utf-8 -*-
"""大模型粗筛：批次打分、全局截断。

设计要点（对应历史问题）：
- 批次只打分不判决：LLM 对每条候选输出 keep + total_score，
  判决延迟到全部批次合并后按全局排名执行，避免批次间标准漂移误杀。
- 输出契约要求 keep=no 只回 index+keep+score（极简），保留项才输出完整字段，
  控制输出 token，根治 100 条/批时超出 max_tokens 被截断导致的 parse fail。
- 解析容忍截断：整体 JSON 解析失败时，抢救数组中完整闭合的对象。
- LLM 整批失败时走启发式兜底（weight/HN热度/GitHub星标），不再全保留。
"""
import json
from typing import List, Dict, Optional, Tuple

from core.llm_client import chat_completion, safe_json_parse
from core.skill_loader import load_skill_prompt


class Selector:
    """AI 行业情报粗筛器。"""

    BATCH_SIZE = 100      # 每批候选数（受输入 token 限制，不宜再大）
    SCORE_FLOOR = 15      # 全局分数线：yes 且 ≥15 进全局排名（25 误杀压线条目，15 召回优先）
    GLOBAL_TOP_N = 80     # 全局名额：进下游（去重/聚类/精排）的最大条数
    FALLBACK_MAX = 30     # 启发式兜底时单批最多保留条数

    def __init__(self):
        self.system_prompt = load_skill_prompt("rss-audit-screener")

    # ── 主流程 ──

    def screen(self, candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """输入候选池，分批打分、全局截断，返回 (日报保留, 深度池候选)。"""
        if not candidates:
            return [], []

        total = len(candidates)
        all_scored: List[Dict] = []
        all_deep: List[Dict] = []
        batch_total = (total + self.BATCH_SIZE - 1) // self.BATCH_SIZE

        for batch_start in range(0, total, self.BATCH_SIZE):
            batch = candidates[batch_start : batch_start + self.BATCH_SIZE]
            batch_num = batch_start // self.BATCH_SIZE + 1
            print(f"  [FILTER batch {batch_num}/{batch_total}] 处理 {len(batch)} 条候选...")

            try:
                resp = chat_completion(
                    system=self.system_prompt,
                    user=self._format_candidates(batch),
                    task="screen",
                    timeout=120,
                )
                matched, salvaged = self._annotate_batch(resp, batch)
                # 截断抢救且覆盖率过低：未标注条目不能静默丢弃，走启发式打分
                unannotated = [c for c in batch if "keep" not in c]
                if salvaged and matched < len(batch) * 0.5 and unannotated:
                    print(f"  ⚠️ 批次覆盖率过低（{matched}/{len(batch)}），"
                          f"未标注 {len(unannotated)} 条转启发式兜底")
                    self._heuristic_fallback(unannotated)
            except Exception as e:
                print(f"  ⚠️ 批次 {batch_num} LLM 失败: {e}，启用启发式兜底")
                self._heuristic_fallback(batch)

            for c in batch:
                if c.get("keep") in ("strong", "yes"):
                    all_scored.append(c)
                if c.get("deep_dive_candidate") is True:
                    all_deep.append(c)

        # ── 全局截断：strong 直通（不占名额），yes 按分数全局排序取 top N ──
        strong = [c for c in all_scored if c.get("keep") == "strong"]
        yes = [c for c in all_scored
               if c.get("keep") == "yes" and (c.get("total_score") or 0) >= self.SCORE_FLOOR]
        yes.sort(key=lambda x: x.get("total_score") or 0, reverse=True)
        kept = strong + yes[: self.GLOBAL_TOP_N]

        # 深度池去重（按 URL）
        seen = set()
        deduped_deep = []
        for c in all_deep:
            link = c.get("link", "")
            if link not in seen:
                seen.add(link)
                deduped_deep.append(c)

        # 分数分布统计：观察模型打分是否坍塌（人人同分则说明 prompt 失效）
        scores = [c.get("total_score") for c in all_scored if c.get("total_score")]
        if scores:
            scores.sort()
            mid = scores[len(scores) // 2]
            print(f"  分数分布: min={scores[0]} 中位={mid} max={scores[-1]} 有分={len(scores)}/{total}")
        print(f"  ✅ 粗筛全局保留: {len(kept)} / {total}"
              f"（strong {len(strong)} + 达线 {len(yes)} 取前 {min(len(yes), self.GLOBAL_TOP_N)}）"
              f" | 深度池: {len(deduped_deep)}")
        return kept, deduped_deep

    # ── 批次标注 ──

    def _annotate_batch(self, raw: str, batch: List[Dict]) -> Tuple[int, bool]:
        """把 LLM 结果写回候选 item（keep/total_score/dimension_scores/reason 等）。

        匹配优先用 index（输入编号，1 起）；模型不遵医嘱时回退标题精确匹配。
        不使用子串匹配——空 title 恒真错配，改写标题会丢失结果。
        未被模型返回的条目保持 keep 未设置（= 不保留）。
        返回 (命中条数, 是否走了截断抢救路径)。
        """
        results, salvaged = self._parse_llm_array(raw)

        def _match(r: Dict) -> Optional[Dict]:
            idx = r.get("index")
            if isinstance(idx, int) and 1 <= idx <= len(batch):
                return batch[idx - 1]
            title = r.get("title", "")
            if title:  # 空标题绝不参与匹配
                for c in batch:
                    if c["title"] == title:
                        return c
            return None

        matched = 0
        for r in results:
            c = _match(r)
            if c is None:
                continue
            matched += 1
            keep = r.get("keep", "")
            c["keep"] = keep
            c["total_score"] = r.get("total_score")
            c["dimension_scores"] = r.get("dimension_scores", {})
            c["reason"] = r.get("reason", "")
            c["audit_mapping_guess"] = r.get("audit_mapping_guess") or r.get("industry_mapping", "")
            # 兼容下游旧字段名
            c["keep_reason"] = c["reason"]
            c["industry_mapping"] = c["audit_mapping_guess"]
            if keep in ("strong", "yes"):
                c["deep_dive_candidate"] = r.get("deep_dive_candidate", False)
                c["deep_dive_reason"] = r.get("deep_dive_reason", "")

        tag = "（截断抢救）" if salvaged else ""
        print(f"  ✅ 批次标注{tag}: 命中 {matched} / {len(batch)}")
        return matched, salvaged

    @staticmethod
    def _extract_balanced_array(t: str) -> Optional[str]:
        """从第一个 '[' 起提取配平的 JSON 数组文本（字符串感知）。
        容忍围栏外的汇总句等游离文本；找不到配平右括号时返回 None。"""
        start = t.find("[")
        if start == -1:
            return None
        depth, in_str, esc = 0, False, False
        for i in range(start, len(t)):
            ch = t[i]
            if in_str:
                if esc:
                    esc = False
                elif ch == "\\":
                    esc = True
                elif ch == '"':
                    in_str = False
                continue
            if ch == '"':
                in_str = True
            elif ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
                if depth == 0:
                    return t[start : i + 1]
        return None

    @staticmethod
    def _parse_llm_array(raw: str) -> Tuple[List[Dict], bool]:
        """解析 LLM 返回的 JSON 数组；失败时逐层降级。

        降级链：整体解析 → 提取配平数组解析（容忍尾部汇总句/围栏）
        → 逐对象抢救（容忍截断）。返回 (对象列表, 是否走了降级路径)。
        """
        parsed = safe_json_parse(raw)
        if isinstance(parsed, list):
            return [r for r in parsed if isinstance(r, dict)], False

        # 去围栏
        t = raw.strip()
        if t.startswith("```"):
            nl = t.find("\n")
            t = t[nl + 1:] if nl != -1 else t.strip("`")

        # 降级 1：提取配平数组（模型常在数组后附汇总句，整体解析必挂）
        arr = Selector._extract_balanced_array(t)
        if arr:
            try:
                parsed = json.loads(arr)
                if isinstance(parsed, list):
                    print(f"  ⚠️ 整体解析失败，已从围栏/汇总文本中提取数组（{len(parsed)} 条）")
                    return [r for r in parsed if isinstance(r, dict)], True
            except json.JSONDecodeError:
                pass

        # 降级 2：逐对象抢救（容忍尾部被 max_tokens 截断）
        objs: List[Dict] = []
        start = t.find("[")
        if start != -1:
            depth, obj_start, in_str, esc = 0, None, False, False
            for i in range(start, len(t)):
                ch = t[i]
                if in_str:
                    if esc:
                        esc = False
                    elif ch == "\\":
                        esc = True
                    elif ch == '"':
                        in_str = False
                    continue
                if ch == '"':
                    in_str = True
                elif ch == "{":
                    if depth == 0:
                        obj_start = i
                    depth += 1
                elif ch == "}":
                    depth -= 1
                    if depth == 0 and obj_start is not None:
                        try:
                            objs.append(json.loads(t[obj_start : i + 1]))
                        except json.JSONDecodeError:
                            pass
                        obj_start = None

        print(f"  ⚠️ 整体 JSON 解析失败，抢救出 {len(objs)} 条完整记录")
        print(f"     响应头: {raw[:150]!r}")
        print(f"     响应尾: {raw[-150:]!r}")
        return objs, True

    # ── 启发式兜底（LLM 整批失败时） ──

    def _heuristic_fallback(self, batch: List[Dict]) -> None:
        """LLM 不可用时按信号打分，替代旧的"全保留"（避免洪峰灌爆下游）。

        合成分规则：weight 7/8/9/10 → 25/26/27/28；HN热度≥100 或 GitHub星标≥10k → 28。
        单批最多保留 FALLBACK_MAX 条，保持与 LLM 路径相同的全局截断语义。
        """
        survivors = []
        for c in batch:
            w = int(c.get("weight", 5) or 5)
            score = 0
            if w >= 7:
                score = 18 + w
            if (c.get("hn_score") or 0) >= 100 or (c.get("stars") or 0) >= 10000:
                score = max(score, 28)
            if score > 0:
                c["keep"] = "yes"
                c["total_score"] = score
                c["reason"] = "启发式兜底（LLM 不可用，按信源权重/热度打分）"
                c["keep_reason"] = c["reason"]
                survivors.append(c)
        survivors.sort(key=lambda x: x["total_score"], reverse=True)
        for c in survivors[self.FALLBACK_MAX :]:
            c["keep"] = "no"  # 超出兜底名额，撤销保留
        print(f"  启发式兜底保留: {min(len(survivors), self.FALLBACK_MAX)} / {len(batch)}")

    # ── 输入格式化 ──

    def _format_candidates(self, candidates: List[Dict]) -> str:
        """格式化候选为 LLM 输入。除基础字段外，按 skill input_schema 补发
        report_cycle / content_type / stars / hn_score / categories 等信号字段，
        仅在字段有值时输出，避免无意义噪音。"""
        lines = []
        for i, c in enumerate(candidates, 1):
            parts = [
                f"[{i}] {c['title']}",
                f"来源:{c['source']}",
                f"日期:{c.get('date', '')[:10]}",
            ]
            if c.get("report_cycle") and c["report_cycle"] != "daily":
                parts.append(f"周期:{c['report_cycle']}")
            if c.get("content_type") and c["content_type"] != "article":
                parts.append(f"类型:{c['content_type']}")
            if c.get("stars"):
                parts.append(f"GitHub星标:{c['stars']}")
            if c.get("is_new_repo"):
                parts.append("新repo:是")
            if c.get("hn_score"):
                parts.append(f"HN热度:{c['hn_score']}")
            if c.get("categories"):
                cats = ",".join(c["categories"][:5])
                parts.append(f"标签:{cats}")
            parts.append(f"摘要:{c.get('summary', '')[:300]}")
            lines.append(" | ".join(parts))
        return "\n".join(lines)
