# -*- coding: utf-8 -*-
"""日报生成器：调用统一 LLM Client，支持多供应商切换。"""
import json
from typing import Dict, List

from core.llm_client import chat_completion
import config


class Generator:
    """日报生成器。"""

    def __init__(self):
        with open(config.PROMPTS_DIR + "/generator_system.txt", "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

    def generate(self, top3: List[Dict], clusters: List[Dict]) -> str:
        """输入 Top3 新闻 + 完整事件簇，生成 HTML 日报。"""
        user_prompt = self._build_prompt(top3, clusters)
        resp = chat_completion(
            system=self.system_prompt,
            user=user_prompt,
            task="generate",
            temperature=0.5,  # 生成需要一定灵活性
            timeout=180,
        )
        return resp

    def _build_prompt(self, top3: List[Dict], clusters: List[Dict]) -> str:
        enriched = []
        for item in top3:
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
