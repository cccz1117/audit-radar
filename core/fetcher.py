# -*- coding: utf-8 -*-
"""信源采集器：NVD + RSS + NewsNow + HuggingFace Daily Papers。"""
import json
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import List, Dict

import requests

import config


class Fetcher:
    """统一采集器。"""

    def __init__(self):
        with open(config.SOURCES_PATH, "r", encoding="utf-8") as f:
            self.sources = json.load(f)["sources"]

    def fetch_all(self) -> List[Dict]:
        """采集所有启用的信源，返回统一格式候选池。"""
        candidates = []
        for src in self.sources:
            if not src.get("enabled", True):
                continue
            try:
                if src["type"] == "api":
                    items = self._fetch_api(src)
                elif src["type"] == "rss":
                    items = self._fetch_rss(src)
                elif src["type"] == "newsnow":
                    items = self._fetch_newsnow(src)
                else:
                    print(f"  [WARN] unknown source type '{src.get('type')}' for {src.get('name')}")
                    continue
                for item in items:
                    item["source"] = src["name"]
                    item["category"] = src.get("category", "general")
                    item["weight"] = src.get("weight", 5)
                    item["report_cycle"] = src.get("report_cycle", "daily")
                    item["content_type"] = src.get("content_type", "article")
                candidates.extend(items)
                print(f"  [NET] {src['name']}: {len(items)} items")
            except Exception as e:
                print(f"  [WARN] {src['name']} failed: {e}")
        return candidates

    def fetch_with_status(self) -> Dict:
        """采集并返回每个信源的状态，用于监控。"""
        result = {"candidates": [], "sources": []}
        for src in self.sources:
            if not src.get("enabled", True):
                continue
            status = {"name": src["name"], "count": 0, "status": "success", "error": ""}
            try:
                if src["type"] == "api":
                    items = self._fetch_api(src)
                elif src["type"] == "rss":
                    items = self._fetch_rss(src)
                elif src["type"] == "newsnow":
                    items = self._fetch_newsnow(src)
                else:
                    status["status"] = "skipped"
                    status["error"] = f"unknown type {src.get('type')}"
                    result["sources"].append(status)
                    continue
                for item in items:
                    item["source"] = src["name"]
                    item["category"] = src.get("category", "general")
                    item["weight"] = src.get("weight", 5)
                    item["report_cycle"] = src.get("report_cycle", "daily")
                    item["content_type"] = src.get("content_type", "article")
                result["candidates"].extend(items)
                status["count"] = len(items)
                print(f"  [NET] {src['name']}: {len(items)} items")
            except Exception as e:
                status["status"] = "failed"
                status["error"] = str(e)
                print(f"  [WARN] {src['name']} failed: {e}")
            result["sources"].append(status)
        return result

    def _fetch_api(self, src: Dict) -> List[Dict]:
        """API 信源（NVD / HF Papers / HN Algolia）。"""
        url = src["url"]
        if "nvd.nist.gov" in url:
            return self._fetch_nvd(url)
        if "huggingface.co" in url and "daily-papers" in url:
            return self._fetch_hf_papers(url)
        if "hn.algolia.com" in url:
            return self._fetch_hn_algolia(url)
        return []

    def _fetch_nvd(self, url: str) -> List[Dict]:
        """NVD CVSS 4 HIGH/CRITICAL。"""
        resp = requests.get(
            url,
            timeout=config.REQUEST_TIMEOUT,
            headers={"User-Agent": "AuditRadar/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        items = []
        for vuln in data.get("vulnerabilities", [])[: config.NVD_RESULTS_PER_PAGE]:
            cve = vuln["cve"]
            desc = self._extract_description(cve)
            items.append({
                "title": f"{cve['id']} - {desc[:100]}",
                "date": cve.get("published", ""),
                "summary": desc,
                "link": f"https://nvd.nist.gov/vuln/detail/{cve['id']}",
                "raw_score": self._extract_cvss(cve),
            })
        return items

    @staticmethod
    def _extract_description(cve: Dict) -> str:
        for d in cve.get("descriptions", []):
            if d.get("lang") == "en":
                return d["value"]
        return ""

    @staticmethod
    def _extract_cvss(cve: Dict) -> float:
        metrics = cve.get("metrics", {})
        for v in ["cvssMetricV40", "cvssMetricV31", "cvssMetricV30"]:
            if v in metrics:
                return metrics[v][0]["cvssData"]["baseScore"]
        return 0.0

    def _fetch_hf_papers(self, url: str) -> List[Dict]:
        """HuggingFace Daily Papers。"""
        resp = requests.get(url, timeout=config.REQUEST_TIMEOUT)
        resp.raise_for_status()
        papers = resp.json()
        items = []
        for p in papers[: config.RSS_MAX_ITEMS]:
            items.append({
                "title": p.get("title", ""),
                "date": p.get("publishedAt", ""),
                "summary": p.get("summary", ""),
                "link": f"https://huggingface.co/papers/{p.get('paper', {}).get('id', '')}",
                "raw_score": 0,
            })
        return items

    def _fetch_hn_algolia(self, url: str) -> List[Dict]:
        """HN Algolia API：提取 points、comments、title、url。"""
        resp = requests.get(
            url,
            timeout=config.REQUEST_TIMEOUT,
            headers={"User-Agent": "AuditRadar/1.0"},
        )
        resp.raise_for_status()
        data = resp.json()
        items = []
        for hit in data.get("hits", [])[: config.RSS_MAX_ITEMS]:
            points = hit.get("points", 0) or 0
            num_comments = hit.get("num_comments", 0) or 0
            title = hit.get("title", "")
            link = hit.get("url", "")
            # 如果原始文章链接为空，fallback 到 HN 讨论页面
            if not link:
                link = f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
            created_at = hit.get("created_at", "")
            author = hit.get("author", "")
            summary = f"HN {points} 分 | {num_comments} 评论 | 作者 {author}"
            items.append({
                "title": title,
                "date": created_at,
                "summary": summary,
                "link": link,
                "raw_score": points,
                "hn_score": points,
                "num_comments": num_comments,
            })
        return items

    def _fetch_rss(self, src: Dict) -> List[Dict]:
        """RSS 信源通用抓取。支持提取 category 标签。"""
        timeout = src.get("timeout", config.REQUEST_TIMEOUT)
        # 对 The Information 使用浏览器 UA 降低 Cloudflare 拦截概率
        ua = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
            if "theinformation.com" in src.get("url", "")
            else "AuditRadar/1.0"
        )
        resp = self._request_with_retry(
            src["url"],
            headers={"User-Agent": ua},
            timeout=timeout,
        )
        root = ET.fromstring(resp.content)
        items = []
        # 兼容 RSS 2.0 / Atom
        for entry in root.iter("item"):
            title = entry.find("title")
            link = entry.find("link")
            pub_date = entry.find("pubDate")
            desc = entry.find("description")
            enclosure = entry.find("enclosure")
            audio_url = ""
            if enclosure is not None:
                audio_url = enclosure.get("url") or ""
            title_text = title.text if title is not None else ""
            summary_text = self._strip_html(desc.text if desc is not None else "")
            if not summary_text:
                summary_text = title_text

            # 提取 category 标签（AlphaSignal 等源使用）
            categories = []
            for cat in entry.findall("category"):
                if cat.text:
                    categories.append(cat.text)

            # 针对 AlphaSignal 的基础 raw_score（内容质量高）
            raw_score = 0
            if "alphasignal.ai" in src.get("url", ""):
                raw_score = 5  # 基础质量加分
                # security / open source 类别再加权
                if any(c.lower() in ("security", "open source") for c in categories):
                    raw_score += 3

            items.append({
                "title": title_text,
                "date": pub_date.text if pub_date is not None else "",
                "summary": summary_text,
                "link": link.text if link is not None else "",
                "audio_url": audio_url,
                "raw_score": raw_score,
                "categories": categories,
            })
            if len(items) >= config.RSS_MAX_ITEMS:
                break
        # Atom fallback
        if not items:
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):
                title = entry.find("atom:title", ns)
                link = entry.find("atom:link", ns)
                updated = entry.find("atom:updated", ns)
                summary = entry.find("atom:summary", ns)
                audio_url = ""
                for lnk in entry.findall("atom:link", ns):
                    if lnk.get("rel") == "enclosure":
                        audio_url = lnk.get("href") or ""
                        break
                title_text = title.text if title is not None else ""
                summary_text = self._strip_html(summary.text if summary is not None else "")
                if not summary_text:
                    summary_text = title_text

                categories = []
                for cat in entry.findall("atom:category", ns):
                    term = cat.get("term")
                    if term:
                        categories.append(term)

                raw_score = 0
                if "alphasignal.ai" in src.get("url", ""):
                    raw_score = 5
                    if any(c.lower() in ("security", "open source") for c in categories):
                        raw_score += 3

                items.append({
                    "title": title_text,
                    "date": updated.text if updated is not None else "",
                    "summary": summary_text,
                    "link": link.get("href") if link is not None else "",
                    "audio_url": audio_url,
                    "raw_score": raw_score,
                    "categories": categories,
                })
                if len(items) >= config.RSS_MAX_ITEMS:
                    break
        return items

    def _fetch_newsnow(self, src: Dict) -> List[Dict]:
        """NewsNow API 信源。"""
        source_id = src["source_id"]
        url = f"https://newsnow.busiyi.world/api/s?id={source_id}&latest"
        timeout = src.get("timeout", config.REQUEST_TIMEOUT)
        resp = self._request_with_retry(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
                "Accept": "application/json",
            },
            timeout=timeout,
        )
        data = resp.json()
        items = []
        for item in data.get("items", [])[: config.RSS_MAX_ITEMS]:
            pub_date_ms = item.get("pubDate")
            date_str = ""
            if pub_date_ms:
                try:
                    dt = datetime.fromtimestamp(pub_date_ms / 1000, tz=timezone.utc)
                    date_str = dt.isoformat()
                except Exception:
                    date_str = str(pub_date_ms)
            extra = item.get("extra") or {}
            summary = extra.get("hover", "")
            title = item.get("title", "").strip()
            if not summary:
                summary = title  # hover 为空时，用标题作为摘要兜底

            # 解析 GitHub repo 的 star 数（如 "✰ 17,507"）
            stars = 0
            info = extra.get("info", "")
            if info and "✰" in info:
                try:
                    stars = int(info.replace("✰", "").replace(",", "").strip())
                except ValueError:
                    stars = 0

            items.append({
                "title": title,
                "date": date_str,
                "summary": summary,
                "link": item.get("url", ""),
                "raw_score": 0,
                "source_type": "newsnow",
                "stars": stars,
            })
        return items

    @staticmethod
    def _request_with_retry(url: str, headers: Dict, timeout: int, max_retries: int = 2):
        """带重试的 HTTP GET。"""
        last_err = None
        for attempt in range(max_retries + 1):
            try:
                resp = requests.get(url, headers=headers, timeout=timeout)
                resp.raise_for_status()
                return resp
            except Exception as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(1 * (attempt + 1))
        raise last_err

    @staticmethod
    def _strip_html(raw: str) -> str:
        import re
        import html

        if not raw:
            return ""
        text = re.sub(r"<[^>]+>", "", raw)
        return html.unescape(text).strip()
