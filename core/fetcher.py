# -*- coding: utf-8 -*-
"""信源采集器：NVD + RSS + HuggingFace Daily Papers。"""
import json
import xml.etree.ElementTree as ET
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
                else:
                    continue
                for item in items:
                    item["source"] = src["name"]
                    item["category"] = src.get("category", "general")
                    item["weight"] = src.get("weight", 5)
                candidates.extend(items)
                print(f"  📡 {src['name']}: {len(items)} items")
            except Exception as e:
                print(f"  ⚠️ {src['name']} failed: {e}")
        return candidates

    def _fetch_api(self, src: Dict) -> List[Dict]:
        """API 信源（NVD / HF Papers）。"""
        url = src["url"]
        if "nvd.nist.gov" in url:
            return self._fetch_nvd(url)
        if "huggingface.co" in url and "daily-papers" in url:
            return self._fetch_hf_papers(url)
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

    def _fetch_rss(self, src: Dict) -> List[Dict]:
        """RSS 信源通用抓取。"""
        resp = requests.get(
            src["url"],
            timeout=config.REQUEST_TIMEOUT,
            headers={"User-Agent": "AuditRadar/1.0"},
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        items = []
        # 兼容 RSS 2.0 / Atom
        for entry in root.iter("item"):
            title = entry.find("title")
            link = entry.find("link")
            pub_date = entry.find("pubDate")
            desc = entry.find("description")
            items.append({
                "title": title.text if title is not None else "",
                "date": pub_date.text if pub_date is not None else "",
                "summary": self._strip_html(desc.text if desc is not None else ""),
                "link": link.text if link is not None else "",
                "raw_score": 0,
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
                items.append({
                    "title": title.text if title is not None else "",
                    "date": updated.text if updated is not None else "",
                    "summary": self._strip_html(summary.text if summary is not None else ""),
                    "link": link.get("href") if link is not None else "",
                    "raw_score": 0,
                })
                if len(items) >= config.RSS_MAX_ITEMS:
                    break
        return items

    @staticmethod
    def _strip_html(raw: str) -> str:
        import re
        return re.sub(r"<[^>]+>", "", raw).strip()
