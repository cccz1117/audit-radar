# -*- coding: utf-8 -*-
"""月报生成器：调用统一 LLM Client，支持多供应商切换。"""
import json
from typing import List, Dict

from core.llm_client import chat_completion
import config


class WeeklyGenerator:
    """周/月报生成器。"""

    SYSTEM_PROMPT = """\
你是交通银行信息科技审计部的战略分析师。
请基于本周/月的审计日报素材，生成一份结构化复盘报告。

报告结构：
1. 本周/月监管态势总览
2. 模型风险事件追踪
3. 技术安全趋势
4. 下月审计重点建议

输出纯 HTML（三段式布局，与日报风格一致）。
"""

    def __init__(self):
        pass

    def generate(self, deep_dive_candidates: List[Dict]) -> str:
        if not deep_dive_candidates:
            return "<p>本周/月无 deep-dive 素材</p>"

        # 按审计价值排序
        sorted_candidates = sorted(
            deep_dive_candidates,
            key=lambda x: (
                x.get("deep_dive_reason", "").count("AI"),
                x.get("deep_dive_reason", "").count("银行"),
                x.get("date", ""),
            ),
            reverse=True,
        )

        top3 = sorted_candidates[:3]
        user_prompt = json.dumps({"deep_dive_top3": top3}, ensure_ascii=False, indent=2)

        return chat_completion(
            system=self.SYSTEM_PROMPT,
            user=user_prompt,
            task="generate",
            temperature=0.5,
            timeout=180,
        )
