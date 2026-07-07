# -*- coding: utf-8 -*-
"""大模型精排：调用统一 LLM Client，支持多供应商切换。"""
import json
from typing import List, Dict

from core.llm_client import chat_completion, safe_json_parse
import config


class Ranker:
    """审计新闻精排器。"""

    def __init__(self):
        with open(config.PROMPTS_DIR + "/ranker_system.txt", "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

    def rank(self, candidates: List[Dict]) -> Dict:
        """输入共振后的候选，返回 Top3 + Top8 + summary。"""
        if not candidates:
            return {"top3": [], "top8": [], "summary": "当日无有效候选"}
        user_prompt = self._format_candidates(candidates)
        resp = chat_completion(
            system=self.system_prompt,
            user=user_prompt,
            task="rank",
            timeout=60,
        )
        )
        return self._parse_results(resp, candidates)

    def _format_candidates(self, candidates: List[Dict]) -> str:
        lines = ["候选列表（已通过粗筛和共振验证）："]
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"[{i}] {c['event_title']} | 来源:{','.join(c['sources'])} | 类别:{c['categories']} | 共振分:{c.get('resonance_score',0)} | 摘要:{c['items'][0].get('summary','')[:300]}"
            )
        return "\n".join(lines)

    def _parse_results(self, raw: str, candidates: List[Dict]) -> Dict:
        parsed = safe_json_parse(raw)
        if parsed:
            return parsed
        print(f"  ⚠️ Ranker JSON parse failed, fallback")
        top3 = candidates[:3]
        return {
            "top3": [{"rank": i+1, "line": c["categories"][0], "title": c["event_title"]} for i, c in enumerate(top3)],
            "top8": [],
            "summary": "Fallback: 按共振分直接取前3",
        }
