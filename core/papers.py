# -*- coding: utf-8 -*-
"""论文库辅助模块：识别论文候选、保存论文、富化摘要。"""
import re
from typing import Dict, List, Optional


ARXIV_ID_RE = re.compile(r"arxiv\s*[:\-]?\s*(\d{4}\.\d+(?:v\d+)?)", re.IGNORECASE)


def looks_like_paper(item: Dict) -> bool:
    """判断一个候选是否应被当作论文入库。"""
    link = (item.get("link") or "").lower()
    title = (item.get("title") or "").lower()
    source = (item.get("source") or "").lower()
    content_type = (item.get("content_type") or "").lower()

    if content_type == "paper":
        return True
    if "arxiv.org" in link:
        return True
    if "huggingface.co/papers" in link:
        return True
    if "paperswithcode.com" in link:
        return True
    if "arxiv" in source or "huggingface papers" in source:
        return True
    if ARXIV_ID_RE.search(title):
        return True
    return False


def extract_arxiv_id(text: str) -> Optional[str]:
    """从标题或链接中提取 arXiv ID。"""
    match = ARXIV_ID_RE.search(text)
    return match.group(1) if match else None


def normalize_paper_candidate(item: Dict) -> Dict:
    """标准化论文候选字段。"""
    normalized = dict(item)
    link = normalized.get("link", "")
    title = normalized.get("title", "")

    # arXiv 摘要通常来自 <description>，已经是文本
    # 如果没有 abstract 字段，用 summary 兜底
    if not normalized.get("abstract"):
        normalized["abstract"] = normalized.get("summary", "")

    # 提取 arXiv ID 放入 metadata
    arxiv_id = extract_arxiv_id(title) or extract_arxiv_id(link)
    if arxiv_id:
        metadata = normalized.get("metadata", {})
        metadata["arxiv_id"] = arxiv_id
        normalized["metadata"] = metadata

    return normalized


def _might_mention_paper(item: Dict) -> bool:
    """判断候选是否可能在讨论某篇论文。"""
    source = (item.get("source") or "").lower()
    link = (item.get("link") or "").lower()
    title = (item.get("title") or "").lower()

    # 论文源本身
    if looks_like_paper(item):
        return True
    # 微信公众号 RSS 经常解读论文
    if "anyfeeder.com/weixin" in link or "weixin" in source:
        return True
    # Scour 个人 RSS 混合源
    if "scour.ing" in link:
        return True
    # 标题含 "论文"、"paper"、"arxiv" 等词
    if any(k in title for k in ("论文", "paper", "arxiv")):
        return True
    # 标题含 arXiv ID
    if ARXIV_ID_RE.search(title):
        return True
    return False


def enrich_candidates(candidates: List[Dict], storage) -> List[Dict]:
    """对候选进行论文摘要富化：如果提到论文且在库中，补充 abstract。"""
    enriched = []
    for c in candidates:
        item = dict(c)
        summary = item.get("summary", "") or ""

        # 只对可能讨论论文且摘要较短的候选做富化
        if len(summary) < 300 and _might_mention_paper(item):
            paper = None
            # 1. 优先按链接精确匹配
            paper = storage.get_paper_by_link(item.get("link", ""))

            # 2. 按 arXiv ID 匹配
            if not paper:
                arxiv_id = extract_arxiv_id(item.get("title", "")) or extract_arxiv_id(item.get("summary", ""))
                if arxiv_id:
                    results = storage.search_papers_by_title(arxiv_id, days=30)
                    if results:
                        paper = results[0]

            # 3. 按标题关键词模糊匹配
            if not paper:
                keywords = _extract_title_keywords(item.get("title", ""))
                if keywords:
                    results = storage.search_papers_by_title(keywords, days=30)
                    if results:
                        paper = results[0]

            if paper and paper.get("abstract") and len(paper["abstract"]) > len(summary):
                item["summary"] = f"{summary}\n[论文摘要] {paper['abstract']}".strip()
                item["paper_enriched"] = True

        enriched.append(item)
    return enriched


# 简单停用词
_STOP_WORDS = {"the", "a", "an", "in", "on", "of", "for", "and", "or", "to", "with", "is", "are"}


def _extract_title_keywords(title: str) -> str:
    """从标题中提取最有区分度的几个词，用于模糊搜索。"""
    words = re.findall(r"[a-z0-9]{3,}", title.lower())
    filtered = [w for w in words if w not in _STOP_WORDS]
    return " ".join(filtered[:5])
