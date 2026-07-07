# -*- coding: utf-8 -*-
"""去重模块：调用统一 LLM Client，支持多供应商切换。"""
import json
from typing import List, Dict, Optional

from core.llm_client import chat_completion, safe_json_parse
import config


class DedupAI:
    """基于语义相似度的 AI 去重器。"""

    SYSTEM_PROMPT = """\
你是一个去重专家。请判断以下两条新闻是否描述同一事件。

判断标准：
- 同一事件：核心事实（人、时、地、事）相同，即使标题措辞不同
- 不同事件：核心事实不同，或只是同一主题的不同侧面

输出严格 JSON：{"is_duplicate": true/false, "confidence": 0-1, "reason": "..."}
"""

    def __init__(self):
        pass

    def is_duplicate(self, item_a: Dict, item_b: Dict) -> bool:
        """判断两条新闻是否为同一事件。"""
        if not config.DEDUP_USE_AI:
            return False

        user_prompt = f"""
新闻 A：{item_a.get('title', '')}
摘要：{item_a.get('summary', '')[:500]}

新闻 B：{item_b.get('title', '')}
摘要：{item_b.get('summary', '')[:500]}
"""
        try:
            resp = chat_completion(
                system=self.SYSTEM_PROMPT,
                user=user_prompt,
                task="dedup",
                temperature=0.0,
                max_tokens=100,
                timeout=30,
            )
            result = safe_json_parse(resp)
            if result:
                return result.get("is_duplicate", False)
        except Exception as e:
            print(f"  ⚠️ AI 去重失败: {e}")
        return False


def dedup_pipeline(candidates: List[Dict]) -> List[Dict]:
    """对候选池进行去重。"""
    if not config.DEDUP_USE_AI:
        return candidates

    deduper = DedupAI()
    unique = []
    for c in candidates:
        is_dup = any(deduper.is_duplicate(c, u) for u in unique)
        if not is_dup:
            unique.append(c)
    print(f"  ✅ 去重后: {len(unique)} / {len(candidates)}")
    return unique
