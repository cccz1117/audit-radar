# -*- coding: utf-8 -*-
"""大模型粗筛：调用百炼 API 执行 rss-audit-screener 规则。"""
import json
from typing import List, Dict, Tuple

import requests

import config
from core.skill_loader import load_skill_prompt


class Selector:
    """审计新闻粗筛器。"""

    def __init__(self):
        self.system_prompt = load_skill_prompt("rss-audit-screener")

    def screen(self, candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """输入候选池，返回 (日报保留条目, 深度挖掘候选条目)。"""
        if not candidates:
            return [], []
        user_prompt = self._format_candidates(candidates)
        resp = self._call_llm(user_prompt)
        return self._parse_results(resp, candidates)

    def _format_candidates(self, candidates: List[Dict]) -> str:
        lines = []
        for i, c in enumerate(candidates, 1):
            cycle = c.get("report_cycle", "daily")
            ctype = c.get("content_type", "article")
            audio_info = ""
            if c.get("audio_url"):
                audio_info = f" | 音频:{c['audio_url'][:80]}"
            lines.append(
                f"[{i}] {c.get('title','')} | 来源:{c.get('source','')} | 周期:{cycle} | 类型:{ctype} | 日期:{c.get('date','')[:10]} | 摘要:{c.get('summary','')[:300]}{audio_info}"
            )
        return "\n".join(lines)

    def _call_llm(self, user_prompt: str) -> str:
        """调用百炼 API（DeepSeek-V4-Flash）。"""
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
        if config.DEBUG:
            print(f"  [DEBUG] LLM input: {len(user_prompt)} chars")
        r = requests.post(
            f"{config.DASHSCOPE_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=120,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]
        if config.DEBUG:
            print(f"  [DEBUG] LLM output: {content[:500]}")
        return content

    def _parse_results(self, raw: str, candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """解析模型返回的 JSON 数组。兼容 markdown 代码块。"""
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            results = json.loads(text)
        except json.JSONDecodeError:
            print(f"  [WARN] JSON parse failed, fallback to default rules")
            return self._fallback_split(candidates)

        kept = []
        deep_dive = []
        for r in results:
            matched = self._match_candidate(r.get("title", ""), candidates)
            if not matched:
                continue
            matched["keep"] = r.get("keep", "no")
            matched["keep_reason"] = r.get("reason", "")
            matched["audit_mapping_guess"] = r.get("audit_mapping_guess", "")
            matched["total_score"] = r.get("total_score", 0)
            matched["dimension_scores"] = r.get("dimension_scores", {})
            matched["deep_dive_candidate"] = bool(r.get("deep_dive_candidate", False))
            matched["deep_dive_reason"] = r.get("deep_dive_reason", "")

            # 日报保留：所有源（含 weekly）只要 keep=yes/strong 都可以进日报
            if r.get("keep") in ("strong", "yes"):
                kept.append(matched)
            # 深度池：weekly/monthly 源且被判定为 deep_dive_candidate 的进入周报/月报池
            if matched.get("report_cycle", "daily") != "daily" and matched.get("deep_dive_candidate"):
                deep_dive.append(matched)

        print(f"  [OK] screen: daily {len(kept)} / {len(candidates)}, deep-dive {len(deep_dive)} / {len(candidates)}")
        return kept, deep_dive

    @staticmethod
    def _match_candidate(title: str, candidates: List[Dict]) -> Dict:
        """按标题匹配原始候选。"""
        for c in candidates:
            c_title = c.get("title", "")
            if c_title == title or title in c_title or c_title in title:
                return c
        return {}

    def _fallback_split(self, candidates: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
        """LLM 解析失败时的兜底规则。"""
        kept = []
        deep_dive = []
        for c in candidates:
            if c.get("report_cycle", "daily") != "daily":
                # weekly/monthly 源：同时进日报（保守保留）和深度池
                c["deep_dive_candidate"] = True
                c["deep_dive_reason"] = "LLM fallback: weekly source auto-queued"
                c["audit_mapping_guess"] = "to be judged in weekly report"
                c["keep_reason"] = "LLM fallback: weekly source also kept for daily"
                c["total_score"] = 0
                deep_dive.append(c)
                kept.append(c)
            else:
                c["keep_reason"] = "LLM fallback: daily source auto-kept"
                c["audit_mapping_guess"] = ""
                c["total_score"] = 0
                kept.append(c)
        print(f"  [WARN] fallback: daily {len(kept)}, deep-dive {len(deep_dive)}")
        return kept, deep_dive
