# -*- coding: utf-8 -*-
"""跨天去重：URL 粗筛 + 摘要 Jaccard 预筛 + AI 批量精筛。"""
import hashlib
import re
from typing import Dict, List, Tuple

import requests

import config


def _url_hash(link: str) -> str:
    return hashlib.md5(link.encode("utf-8")).hexdigest() if link else ""


def url_dedup(candidates: List[Dict], is_reported_func) -> Tuple[List[Dict], List[Dict]]:
    """URL 去重：过滤掉最近已报道过的链接。"""
    kept, filtered = [], []
    for c in candidates:
        link = c.get("link", "") or ""
        if link and is_reported_func(_url_hash(link)):
            filtered.append(c)
        else:
            kept.append(c)
    return kept, filtered


def _tokenize(text: str) -> set:
    """简单分词：英文单词、数字、中文字符。"""
    text = text.lower() if text else ""
    words = re.findall(r"[a-z0-9]+", text)
    chars = re.findall(r"[\u4e00-\u9fff]", text)
    return set(words + chars)


def jaccard_similarity(a: Dict, b: Dict) -> float:
    """只比较摘要的 Jaccard 相似度。"""
    tokens_a = _tokenize(a.get("summary", ""))
    tokens_b = _tokenize(b.get("summary", ""))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union)


def jaccard_dedup(
    screened: List[Dict],
    past_items: List[Dict],
    high_threshold: float = 0.85,
) -> Tuple[List[Dict], List[Dict]]:
    """Jaccard 预筛：只去掉高置信度重复的。

    Returns:
        (保留项, 已过滤项)
    """
    if not past_items:
        return screened, []

    kept, filtered = [], []
    for item in screened:
        max_sim = max(jaccard_similarity(item, past) for past in past_items)
        if max_sim >= high_threshold:
            filtered.append(item)
        else:
            kept.append(item)
    return kept, filtered


def _call_llm(prompt: str) -> str:
    """调用百炼 API。"""
    if not config.DASHSCOPE_API_KEY:
        return "none"

    headers = {
        "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": config.MODEL_NAME,
        "messages": [
            {"role": "system", "content": "你只输出编号或 none，不要解释。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.0,
        "max_tokens": 50,
    }
    try:
        r = requests.post(
            f"{config.DASHSCOPE_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=60,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip().lower()
    except Exception:
        return "none"


def ai_batch_dedup(screened: List[Dict], past_items: List[Dict]) -> List[Dict]:
    """AI 批量去重：一次性判断所有候选是否与历史报道重复。"""
    if not past_items or not screened:
        return screened

    prompt = _build_batch_prompt(screened, past_items)
    answer = _call_llm(prompt)

    if answer == "none" or not answer:
        return screened

    # 解析重复编号
    duplicate_indices = set()
    for part in answer.split(","):
        part = part.strip()
        if part.isdigit():
            idx = int(part) - 1  # 编号从 1 开始
            if 0 <= idx < len(screened):
                duplicate_indices.add(idx)

    return [item for i, item in enumerate(screened) if i not in duplicate_indices]


def _build_batch_prompt(screened: List[Dict], past_items: List[Dict]) -> str:
    """构建批量去重 prompt。"""
    lines = [
        "你是银行信息科技审计情报编辑。请判断以下'今日候选新闻'中，哪些与'已报道新闻'本质上是同一事件。",
        "",
        "已报道新闻（最近7天）：",
    ]
    for i, past in enumerate(past_items, 1):
        lines.append(f"{i}. [{past.get('date', '')}] {past.get('title', '')}")

    lines.extend(["", "今日候选新闻："])
    for i, item in enumerate(screened, 1):
        lines.append(f"{i}. 标题：{item.get('title', '')}")
        lines.append(f"   摘要：{item.get('summary', '')}")

    lines.extend(
        [
            "",
            "请输出重复候选的编号（用逗号分隔），如 '1,3'。如果没有重复，输出 'none'。",
            "",
            "判断标准：",
            "- 同一监管文件、同一CVE、同一公司同一问题、同一事件 → 重复",
            "- 同一主题但不同事件 → 不重复",
        ]
    )
    return "\n".join(lines)


def dedup_pipeline(
    candidates: List[Dict],
    screened: List[Dict],
    is_reported_func,
    past_items: List[Dict],
    use_ai: bool = False,
) -> Dict:
    """完整去重流程：URL 粗筛 + 摘要 Jaccard 预筛 + AI 批量精筛。"""
    # 1. URL 粗筛
    url_kept, url_filtered = url_dedup(candidates, is_reported_func)

    # 2. Jaccard 预筛（只比较摘要，高阈值）
    jac_kept, jac_filtered = jaccard_dedup(screened, past_items, high_threshold=0.85)

    # 3. AI 批量精筛
    ai_kept = ai_batch_dedup(jac_kept, past_items) if use_ai else jac_kept

    return {
        "url_kept": url_kept,
        "url_filtered": url_filtered,
        "jaccard_kept": jac_kept,
        "jaccard_filtered": jac_filtered,
        "ai_kept": ai_kept,
        "final_kept": ai_kept,
    }
