# -*- coding: utf-8 -*-
"""大模型粗筛：调用统一 LLM Client，支持多供应商切换。"""
import json
from typing import List, Dict

from core.llm_client import chat_completion, safe_json_parse
from core.skill_loader import load_skill_prompt


class Selector:
    """AI 行业情报粗筛器。"""

    def __init__(self):
        self.system_prompt = load_skill_prompt("rss-audit-screener")

    def screen(self, candidates: List[Dict]) -> tuple[List[Dict], List[Dict]]:
        """输入候选池，分批处理，每批最多 100 条，返回 (日报保留, 深度池候选)。"""
        if not candidates:
            return [], []

        BATCH_SIZE = 100
        all_kept = []
        all_deep = []
        total = len(candidates)

        for batch_start in range(0, total, BATCH_SIZE):
            batch = candidates[batch_start : batch_start + BATCH_SIZE]
            batch_num = batch_start // BATCH_SIZE + 1
            batch_total = (total + BATCH_SIZE - 1) // BATCH_SIZE
            print(f"  [FILTER batch {batch_num}/{batch_total}] 处理 {len(batch)} 条候选...")

            user_prompt = self._format_candidates(batch)
            try:
                resp = chat_completion(
                    system=self.system_prompt,
                    user=user_prompt,
                    task="screen",
                    timeout=120,
                )
                kept, deep_dive = self._parse_results(resp, batch)
            except Exception as e:
                print(f"  ⚠️ 批次 {batch_num} LLM 失败: {e}，fallback 保留该批全部")
                kept = batch
                deep_dive = []

            all_kept.extend(kept)
            all_deep.extend(deep_dive)

        # 深度池去重（按 URL hash）
        seen = set()
        deduped_deep = []
        for c in all_deep:
            link = c.get("link", "")
            if link not in seen:
                seen.add(link)
                deduped_deep.append(c)

        print(f"  ✅ 粗筛总计保留: {len(all_kept)} / {total} | 深度池: {len(deduped_deep)}")
        return all_kept, deduped_deep

    def _format_candidates(self, candidates: List[Dict]) -> str:
        lines = []
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"[{i}] {c['title']} | 来源:{c['source']} | 日期:{c.get('date','')[:10]} | 摘要:{c.get('summary','')[:300]}"
            )
        return "\n".join(lines)

    def _parse_results(self, raw: str, candidates: List[Dict]) -> tuple[List[Dict], List[Dict]]:
        """解析模型返回的 JSON 数组。兼容 markdown 代码块。"""
        results = safe_json_parse(raw)
        if not isinstance(results, list):
            print(f"  ⚠️ JSON parse failed, fallback to text scan")
            return candidates, []  # 保守：全部保留，无深度池
        kept = []
        deep_dive = []
        for r in results:
            if r.get("keep") in ("strong", "yes"):
                for c in candidates:
                    if c["title"] == r.get("title", "") or r.get("title", "") in c["title"]:
                        c["keep_reason"] = r.get("reason", "")
                        c["industry_mapping"] = r.get("industry_mapping", "")
                        c["total_score"] = r.get("total_score", 0)
                        c["deep_dive_candidate"] = r.get("deep_dive_candidate", False)
                        c["deep_dive_reason"] = r.get("deep_dive_reason", "")
                        kept.append(c)
                        break
            if r.get("deep_dive_candidate") is True:
                for c in candidates:
                    if c["title"] == r.get("title", "") or r.get("title", "") in c["title"]:
                        if c not in deep_dive:
                            deep_dive.append(c)
                        break
        print(f"  ✅ 粗筛保留: {len(kept)} / {len(candidates)} | 深度池: {len(deep_dive)}")
        return kept, deep_dive
