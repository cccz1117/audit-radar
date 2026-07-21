# -*- coding: utf-8 -*-
"""大模型精排：调用统一 LLM Client，支持多供应商切换。"""
import json
from typing import List, Dict

from core.llm_client import chat_completion, safe_json_parse
from core.skill_loader import load_skill_prompt


class Ranker:
    """AI 行业情报精排器。"""

    def __init__(self):
        self.system_prompt = load_skill_prompt("audit-news-ranker")

    def rank(self, candidates: List[Dict]) -> Dict:
        """输入共振后的候选，返回 selected_indices + summary。"""
        if not candidates:
            return {"selected_indices": [], "summary": "当日无有效候选"}
        user_prompt = self._format_candidates(candidates)
        resp = chat_completion(
            system=self.system_prompt,
            user=user_prompt,
            task="rank",
            timeout=120,
        )
        return self._parse_results(resp, candidates)

    def _format_candidates(self, candidates: List[Dict]) -> str:
        lines = ["候选列表（已通过粗筛和共振验证），每个候选前面有 [i] 编号。请选出 8 个最值得报道的候选，按优先级排序（前 5 个用于生成日报正文）："]
        for i, c in enumerate(candidates):
            summary_text = (c["items"][0].get("summary", "")[:300] if c.get("items") else "N/A")
            lines.append(
                f"[{i}] {c['event_title']} | 来源:{','.join(c['sources'])} | 类别:{c['categories']} | 共振分:{c.get('resonance_score',0)} | 摘要:{summary_text}"
            )
        return "\n".join(lines)

    def _parse_results(self, raw: str, candidates: List[Dict]) -> Dict:
        parsed = safe_json_parse(raw)
        if parsed and isinstance(parsed.get("selected_indices"), list):
            return parsed
        print(f"  ⚠️ Ranker JSON parse failed, fallback")
        return {
            "selected_indices": list(range(min(8, len(candidates)))),
            "summary": "Fallback: 按共振分直接取前8",
        }
