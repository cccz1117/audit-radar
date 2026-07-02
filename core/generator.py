# -*- coding: utf-8 -*-
"""日报生成器：调用百炼 API 生成结构化审计日报 HTML。"""
import json
from typing import Dict, List

import requests

import config


class Generator:
    """日报生成器。"""

    def __init__(self):
        with open(config.PROMPTS_DIR + "/generator_system.txt", "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

    def generate(self, top3: List[Dict], clusters: List[Dict]) -> str:
        """输入 Top3 新闻 + 完整事件簇，生成 HTML 日报。"""
        user_prompt = self._build_prompt(top3, clusters)
        resp = self._call_llm(user_prompt)
        return resp

    def _build_prompt(self, top3: List[Dict], clusters: List[Dict]) -> str:
        # 为 Top3 补充完整素材
        enriched = []
        for item in top3:
            # 找到对应 cluster
            for c in clusters:
                if c["event_title"] == item.get("title") or item.get("title", "") in c["event_title"]:
                    enriched.append({
                        "title": c["event_title"],
                        "line": item.get("line", "general"),
                        "sources": c["sources"],
                        "resonance_score": c.get("resonance_score", 0),
                        "resonance_level": c.get("level", "low"),
                        "items": [
                            {
                                "title": x["title"],
                                "source": x["source"],
                                "date": x.get("date", "")[:10],
                                "summary": x.get("summary", ""),
                                "link": x.get("link", ""),
                            }
                            for x in c["items"]
                        ],
                    })
                    break
        return json.dumps({"top3": enriched, "date": "今日", "mode": "draft"}, ensure_ascii=False, indent=2)

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
            "temperature": 0.5,  # 生成需要一定灵活性
            "max_tokens": config.MODEL_MAX_TOKENS,
        }
        r = requests.post(
            f"{config.DASHSCOPE_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]
