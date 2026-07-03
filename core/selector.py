# -*- coding: utf-8 -*-
"""大模型粗筛：调用百炼 API 执行 rss-audit-screener 规则。"""
import json
from typing import List, Dict

import requests

import config


class Selector:
    """审计新闻粗筛器。"""

    def __init__(self):
        with open(config.PROMPTS_DIR + "/selector_system.txt", "r", encoding="utf-8") as f:
            self.system_prompt = f.read()

    def screen(self, candidates: List[Dict]) -> List[Dict]:
        """输入候选池，返回 keep=strong/yes 的条目。"""
        if not candidates:
            return []
        user_prompt = self._format_candidates(candidates)
        resp = self._call_llm(user_prompt)
        return self._parse_results(resp, candidates)

    def _format_candidates(self, candidates: List[Dict]) -> str:
        lines = []
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"[{i}] {c['title']} | 来源:{c['source']} | 日期:{c.get('date','')[:10]} | 摘要:{c.get('summary','')[:300]}"
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

    def _parse_results(self, raw: str, candidates: List[Dict]) -> List[Dict]:
        """解析模型返回的 JSON 数组。兼容 markdown 代码块。"""
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            results = json.loads(text)
        except json.JSONDecodeError:
            # fallback：逐行提取 keep=yes/strong 的
            print(f"  [WARN] JSON parse failed, fallback to text scan")
            return candidates  # 保守：全部保留
        kept = []
        for r in results:
            if r.get("keep") in ("strong", "yes"):
                # 找到原始候选匹配
                for c in candidates:
                    if c["title"] == r.get("title", "") or r.get("title", "") in c["title"]:
                        c["keep_reason"] = r.get("reason", "")
                        c["audit_mapping"] = r.get("audit_mapping_guess", "")
                        c["total_score"] = r.get("total_score", 0)
                        kept.append(c)
                        break
        print(f"  [OK] 粗筛保留: {len(kept)} / {len(candidates)}")
        return kept
