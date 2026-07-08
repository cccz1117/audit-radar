# -*- coding: utf-8 -*-
"""去重模块：URL 去重 + Jaccard 内容去重 + AI 灰色地带判断。"""
import hashlib
from typing import List, Dict, Callable

from core.llm_client import chat_completion, safe_json_parse
import config


def _url_hash(link: str) -> str:
    return hashlib.sha256(link.encode("utf-8")).hexdigest()[:32] if link else ""


def _jaccard_similarity(a: str, b: str) -> float:
    """基于字符 bigram 的 Jaccard 相似度。"""

    def _bigrams(text: str):
        text = text.lower().strip()
        return set(text[i : i + 2] for i in range(len(text) - 1))

    set_a = _bigrams(a)
    set_b = _bigrams(b)

    if not set_a and not set_b:
        return 1.0
    if not set_a or not set_b:
        return 0.0

    intersection = len(set_a & set_b)
    union = len(set_a | set_b)
    return intersection / union


class DedupAI:
    """基于语义相似度的 AI 去重器（用于 Jaccard 0.2~0.8 灰色地带）。"""

    SYSTEM_PROMPT = """\
你是一个去重专家。请判断以下两条新闻是否描述同一事件。

判断标准：
- 同一事件：核心事实（人、时、地、事）相同，即使标题措辞不同
- 不同事件：核心事实不同，或只是同一主题的不同侧面

输出严格 JSON：{"is_duplicate": true/false, "confidence": 0-1, "reason": "..."}
"""

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


def dedup_pipeline(
    candidates_raw: List[Dict],
    candidates_screened: List[Dict],
    url_filter_fn: Callable[[str], bool],
    past_items: List[Dict],
    use_ai: bool = False,
) -> Dict:
    """URL + Jaccard + AI 三级去重。

    逻辑：
      1. URL 去重：url_filter_fn(url_hash) 返回 True → 过滤
      2. Jaccard 内容去重（基于摘要）：
         - < 0.2 → 直接保留
         - > 0.8 → 直接过滤
         - 0.2~0.8 → AI 判断（use_ai=True 时）

    返回格式兼容 index.py：
        {
            "url_kept": [...],
            "url_filtered": [...],
            "final_kept": [...],
            "jaccard_filtered": [...],
            "jaccard_kept": [...],
            "ai_kept": [...],
        }
    """
    all_candidates = list(candidates_raw) + list(candidates_screened)

    # ── 1. URL 去重 ──
    url_kept = []
    url_filtered = []
    for c in all_candidates:
        link = c.get("link", "") or ""
        h = _url_hash(link)
        if h and url_filter_fn(h):
            url_filtered.append(c)
        else:
            url_kept.append(c)

    # ── 2. Jaccard 内容去重 ──
    jaccard_filtered = []
    jaccard_kept = []
    ai_kept = []

    for c in url_kept:
        max_sim = 0.0
        closest_past = None

        for p in past_items:
            sim = _jaccard_similarity(
                c.get("summary", "") or "",
                p.get("summary", "") or "",
            )
            if sim > max_sim:
                max_sim = sim
                closest_past = p

        if max_sim < 0.2:
            jaccard_kept.append(c)
        elif max_sim > 0.8:
            jaccard_filtered.append(c)
        else:
            # 灰色地带
            if use_ai and closest_past:
                if DedupAI().is_duplicate(c, closest_past):
                    jaccard_filtered.append(c)
                else:
                    ai_kept.append(c)
            else:
                # AI 未启用或无历史数据：保守过滤
                jaccard_filtered.append(c)

    final_kept = jaccard_kept + ai_kept

    return {
        "url_kept": url_kept,
        "url_filtered": url_filtered,
        "final_kept": final_kept,
        "jaccard_filtered": jaccard_filtered,
        "jaccard_kept": jaccard_kept,
        "ai_kept": ai_kept,
    }
