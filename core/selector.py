# -*- coding: utf-8 -*-
"""大模型粗筛：调用统一 LLM Client，支持多供应商切换。"""
import json
from typing import List, Dict

from core.llm_client import chat_completion, safe_json_parse
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
        resp = chat_completion(
            system=self.system_prompt,
            user=user_prompt,
            task="screen",
            timeout=120,
        )
        return self._parse_results(resp, candidates)

    def _format_candidates(self, candidates: List[Dict]) -> str:
        lines = []
        for i, c in enumerate(candidates, 1):
            lines.append(
                f"[{i}] {c['title']} | 来源:{c['source']} | 日期:{c.get('date','')[:10]} | 摘要:{c.get('summary','')[:300]}"
            )
        return "\n".join(lines)

    def _parse_results(self, raw: str, candidates: List[Dict]) -> List[Dict]:
        """解析模型返回的 JSON 数组。兼容 markdown 代码块。"""
        results = safe_json_parse(raw)
        if not isinstance(results, list):
            print(f"  ⚠️ JSON parse failed, fallback to text scan")
            return candidates  # 保守：全部保留
        kept = []
        for r in results:
            if r.get("keep") in ("strong", "yes"):
                for c in candidates:
                    if c["title"] == r.get("title", "") or r.get("title", "") in c["title"]:
                        c["keep_reason"] = r.get("reason", "")
                        c["audit_mapping"] = r.get("audit_mapping_guess", "")
                        c["total_score"] = r.get("total_score", 0)
                        kept.append(c)
                        break
        print(f"  ✅ 粗筛保留: {len(kept)} / {len(candidates)}")
        return kept
