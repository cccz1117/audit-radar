# -*- coding: utf-8 -*-
"""存储后端抽象基类。"""
from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class StorageBackend(ABC):
    """审计日报数据持久化接口。"""

    @abstractmethod
    def save_candidates(self, date: str, candidates: List[Dict]) -> None:
        """保存原始候选池。"""

    @abstractmethod
    def get_candidates(self, date: str) -> List[Dict]:
        """读取某日原始候选池。"""

    @abstractmethod
    def save_screened(self, date: str, screened: List[Dict]) -> None:
        """保存粗筛结果。"""

    @abstractmethod
    def get_screened(self, date: str) -> List[Dict]:
        """读取某日粗筛结果。"""

    @abstractmethod
    def save_clusters(self, date: str, clusters: List[Dict]) -> None:
        """保存共振事件簇。"""

    @abstractmethod
    def get_clusters(self, date: str) -> List[Dict]:
        """读取某日共振事件簇。"""

    @abstractmethod
    def save_report(self, date: str, report: Dict) -> None:
        """保存生成的日报（HTML + Top3 + summary）。"""

    @abstractmethod
    def get_report(self, date: str) -> Optional[Dict]:
        """读取某日日报。"""

    @abstractmethod
    def record_push(self, date: str, channel: str, status: str, error: str = "") -> None:
        """记录推送状态。"""

    @abstractmethod
    def is_pushed(self, date: str, channel: str) -> bool:
        """某日某渠道是否已成功推送过。"""

    @abstractmethod
    def record_source_status(
        self,
        date: str,
        source: str,
        count: int,
        status: str,
        error: str = "",
    ) -> None:
        """记录单个信源抓取状态。"""

    @abstractmethod
    def save_reported_urls(self, date: str, items: List[Dict]) -> None:
        """保存某日最终入选报道的 URL。"""

    @abstractmethod
    def is_recently_reported(self, url_hash: str, days: int = 7) -> bool:
        """查询 URL 最近 N 天是否已被报道。"""

    @abstractmethod
    def get_recent_report_items(self, days: int = 7) -> List[Dict]:
        """获取最近 N 天已报道的新闻标题和摘要。"""

    @abstractmethod
    def get_repo_history(self, url_hashes: List[str]) -> Dict[str, Dict]:
        """批量查询 repo 历史。"""

    @abstractmethod
    def update_repo_history(self, date: str, repos: List[Dict]) -> None:
        """更新 GitHub repo 历史。"""
