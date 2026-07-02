# -*- coding: utf-8 -*-
"""多源共振简化版：基于关键词聚类，统计独立信源覆盖。"""
from typing import List, Dict
from collections import defaultdict
import re


class ResonanceDetector:
    """事件聚类 + 共振评分。"""

    def detect(self, candidates: List[Dict]) -> List[Dict]:
        """输入粗筛后的候选，输出聚类后的事件簇（含共振分）。"""
        clusters = self._cluster(candidates)
        for cluster in clusters:
            cluster["resonance_score"] = self._calc_score(cluster)
            cluster["level"] = self._level(cluster["resonance_score"])
        # 按共振分排序
        clusters.sort(key=lambda x: x["resonance_score"], reverse=True)
        return clusters

    def _cluster(self, candidates: List[Dict]) -> List[Dict]:
        """基于关键词聚类。"""
        clusters = []
        used = set()
        for i, c in enumerate(candidates):
            if i in used:
                continue
            group = [c]
            used.add(i)
            kw_i = self._extract_keywords(c["title"])
            for j in range(i + 1, len(candidates)):
                if j in used:
                    continue
                kw_j = self._extract_keywords(candidates[j]["title"])
                if len(kw_i & kw_j) >= 2:
                    group.append(candidates[j])
                    used.add(j)
            clusters.append({
                "event_title": c["title"],
                "items": group,
                "sources": list({x["source"] for x in group}),
                "categories": list({x["category"] for x in group}),
            })
        return clusters

    @staticmethod
    def _extract_keywords(title: str) -> set:
        """提取关键词（英文、中文、数字混合）。"""
        title = title.lower()
        # 保留 2+ 字符的词
        words = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]{2,}", title)
        return set(words)

    def _calc_score(self, cluster: Dict) -> int:
        """计算共振分。"""
        sources = cluster["sources"]
        n = len(sources)
        base = n * 10
        # 高权重信源加成
        high_weight = {"Risk.net", "Finextra", "DataCenterDynamics", "nvd-high", "nvd-critical"}
        bonus = sum(5 for s in sources if s in high_weight)
        return base + bonus

    @staticmethod
    def _level(score: int) -> str:
        if score >= 40:
            return "high"
        if score >= 20:
            return "medium"
        if score >= 10:
            return "low"
        return "none"
