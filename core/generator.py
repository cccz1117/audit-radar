# -*- coding: utf-8 -*-
"""日报生成器：调用统一 LLM Client，支持多供应商切换。"""
import json
from typing import Dict, List

from core.llm_client import chat_completion, strip_code_fence
from core.skill_loader import load_skill_prompt


class Generator:
    """IT 监管日报生成器。"""

    def __init__(self):
        self.system_prompt = load_skill_prompt("report-generator")

    def generate(self, selected_indices: List[int], clusters: List[Dict]) -> str:
        """输入选中的 cluster 索引 + 完整事件簇，生成 HTML 日报。"""
        user_prompt = self._build_prompt(selected_indices, clusters)
        resp = chat_completion(
            system=self.system_prompt,
            user=user_prompt,
            task="generate",
            temperature=0.5,
            timeout=60,
        )
        html = strip_code_fence(resp)
        if html != resp.strip():
            print("  [WARN] LLM 输出携带 markdown 代码围栏，已剥离")
        if not html.lstrip().startswith("<"):
            print("  [WARN] 生成结果疑似非 HTML（未以 < 开头），请检查本次输出")
        return html

    def _build_prompt(self, selected_indices: List[int], clusters: List[Dict]) -> str:
        enriched = []
        for idx in selected_indices:
            if idx < 0 or idx >= len(clusters):
                continue
            c = clusters[idx]
            items_data = []
            for x in c.get("items", []):
                entry = {
                    "title": x["title"],
                    "source": x["source"],
                    "date": x.get("date", "")[:10],
                    "summary": x.get("summary", ""),
                }
                items_data.append(entry)
            line = c["categories"][0] if c.get("categories") else "general"
            enriched.append({
                "title": c["event_title"],
                "line": line,
                "sources": c["sources"],
                "resonance_score": c.get("resonance_score", 0),
                "resonance_level": c.get("level", "low"),
                "items": items_data,
            })
        return json.dumps({"candidates": enriched, "date": "今日", "mode": "draft"}, ensure_ascii=False, indent=2)
