# -*- coding: utf-8 -*-
"""日报生成器：调用百炼 API 生成结构化审计日报 HTML。"""
import json
from typing import Dict, List

import requests

import config
from core.skill_loader import load_skill_prompt


class Generator:
    """日报生成器。"""

    def __init__(self):
        self.system_prompt = load_skill_prompt("report-generator")

    def generate(self, top3: List[Dict], clusters: List[Dict], date: str = "今日") -> str:
        """输入 Top3 新闻 + 完整事件簇，生成 HTML 日报。"""
        user_prompt = self._build_prompt(top3, clusters, date)
        resp = self._call_llm(user_prompt)
        return resp

    def _build_prompt(self, top3: List[Dict], clusters: List[Dict], date: str) -> str:
        # 为 Top3 补充完整素材
        enriched = []
        for item in top3:
            title = item.get("title", "")
            matched_cluster = None
            for c in clusters:
                c_title = c.get("event_title", "")
                if c_title == title or title in c_title or c_title in title:
                    matched_cluster = c
                    break
            if matched_cluster:
                enriched.append({
                    "title": matched_cluster["event_title"],
                    "line": item.get("line", "general"),
                    "sources": matched_cluster.get("sources", []),
                    "resonance_score": matched_cluster.get("resonance_score", 0),
                    "resonance_level": matched_cluster.get("level", "low"),
                    "items": [
                        {
                            "title": x.get("title", ""),
                            "source": x.get("source", ""),
                            "date": x.get("date", "")[:10],
                            "summary": x.get("summary", ""),
                            "link": x.get("link", ""),
                        }
                        for x in matched_cluster.get("items", [])
                    ],
                })
            else:
                # 找不到 cluster 时，用 top3 自身字段兜底，避免素材丢失
                enriched.append({
                    "title": title,
                    "line": item.get("line", "general"),
                    "sources": [],
                    "resonance_score": 0,
                    "resonance_level": "low",
                    "items": [{
                        "title": title,
                        "source": "",
                        "date": "",
                        "summary": item.get("summary", ""),
                        "link": item.get("link", ""),
                    }],
                })
        return json.dumps({"top3": enriched, "date": date, "mode": "draft"}, ensure_ascii=False, indent=2)

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
            "temperature": config.MODEL_TEMPERATURE,  # 生成需要一定灵活性
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
