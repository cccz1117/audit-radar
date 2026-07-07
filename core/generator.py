# -*- coding: utf-8 -*-
"""日报生成器：调用统一 LLM Client，支持多供应商切换。"""
import json
from typing import Dict, List

from core.llm_client import chat_completion
from core.skill_loader import load_skill_prompt


class Generator:
    """AI 情报日报生成器。"""

    def __init__(self):
        self.system_prompt = load_skill_prompt("report-generator")

    def generate(self, top3: List[Dict], clusters: List[Dict]) -> str:
        """输入 Top3 新闻 + 完整事件簇，生成 HTML 日报。"""
        user_prompt = self._build_prompt(top3, clusters)
        resp = chat_completion(
            system=self.system_prompt,
            user=user_prompt,
            task="generate",
            temperature=0.5,
            timeout=60,
        )
        return resp

    def _build_prompt(self, top3: List[Dict], clusters: List[Dict]) -> str:
        enriched = []
        for item in top3:
            for c in clusters:
                if c["event_title"] == item.get("title") or item.get("title", "") in c["event_title"]:
                    items_data = []
                    for x in c["items"]:
                        entry = {
                            "title": x["title"],
                            "source": x["source"],
                            "date": x.get("date", "")[:10],
                            "summary": x.get("summary", ""),
                        }
                        # 传递量化信号（如果有）
                        for k in ("hn_score", "stars", "upvotes", "raw_score", "categories", "num_comments"):
                            if k in x:
                                entry[k] = x[k]
                        items_data.append(entry)
                    enriched.append({
                        "title": c["event_title"],
                        "line": item.get("line", "general"),
                        "sources": c["sources"],
                        "resonance_score": c.get("resonance_score", 0),
                        "resonance_level": c.get("level", "low"),
                        "items": items_data,
                    })
                    break
        return json.dumps({"top3": enriched, "date": "今日", "mode": "draft"}, ensure_ascii=False, indent=2)
