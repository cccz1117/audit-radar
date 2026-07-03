# -*- coding: utf-8 -*-
"""大模型精排：调用百炼 API 执行 audit-news-ranker 规则。"""
import json
from typing import List, Dict

import requests

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
        resp = self._call_llm(user_prompt)
        return self._parse_results(resp, candidates)

    def _format_candidates(self, candidates: List[Dict]) -> str:
        lines = ["候选列表（已通过粗筛和共振验证）："]
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"[{i}] {c['event_title']} | 来源:{','.join(c['sources'])} | 类别:{c['categories']} | 共振分:{c.get('resonance_score',0)} | 摘要:{c['items'][0].get('summary','')[:300]}"
            )
        return "\n".join(lines)

    def _call_llm(self, user_prompt: str) -> str:
        headers = {
            "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": config.MODEL_TEMPERATURE,
            "max_tokens": config.MODEL_MAX_TOKENS,
        }
        r = requests.post(
            f"{config.DASHSCOPE_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def _parse_results(self, raw: str, candidates: List[Dict]) -> Dict:
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            print(f"  [WARN] Ranker JSON parse failed, fallback")
            # fallback：取前3条
            top3 = candidates[:3]
            return {
                "top3": [{"rank": i+1, "line": c["categories"][0], "title": c["event_title"]} for i, c in enumerate(top3)],
                "top8": [],
                "summary": "Fallback: 按共振分直接取前3",
            }
