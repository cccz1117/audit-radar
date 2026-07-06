# -*- coding: utf-8 -*-
"""SQLite 存储后端实现。"""
import hashlib
import json
import os
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from .base import StorageBackend


SCHEMA = """
-- 原始候选池
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    crawl_time TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT,
    link TEXT,
    source TEXT NOT NULL,
    source_type TEXT,
    category TEXT,
    published_date TEXT,
    raw_score REAL DEFAULT 0,
    weight INTEGER DEFAULT 5,
    url_hash TEXT UNIQUE,
    raw_data TEXT
);
CREATE INDEX IF NOT EXISTS idx_candidates_date ON candidates(date);
CREATE INDEX IF NOT EXISTS idx_candidates_source ON candidates(source);
CREATE INDEX IF NOT EXISTS idx_candidates_category ON candidates(category);

-- 粗筛结果
CREATE TABLE IF NOT EXISTS screened (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    candidate_id INTEGER,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    keep TEXT NOT NULL,
    total_score INTEGER,
    dimension_scores TEXT,
    category TEXT,
    reason TEXT,
    audit_mapping_guess TEXT
);
CREATE INDEX IF NOT EXISTS idx_screened_date ON screened(date);

-- 共振事件簇
CREATE TABLE IF NOT EXISTS clusters (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    event_title TEXT NOT NULL,
    items TEXT NOT NULL,
    sources TEXT NOT NULL,
    categories TEXT NOT NULL,
    resonance_score INTEGER,
    level TEXT
);
CREATE INDEX IF NOT EXISTS idx_clusters_date ON clusters(date);

-- 日报
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    top3 TEXT NOT NULL,
    summary TEXT,
    html TEXT NOT NULL,
    status TEXT DEFAULT 'draft'
);

-- 推送记录
CREATE TABLE IF NOT EXISTS push_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    channel TEXT NOT NULL,
    pushed_at TEXT NOT NULL,
    status TEXT NOT NULL,
    error TEXT,
    UNIQUE(date, channel)
);

-- 信源抓取状态
CREATE TABLE IF NOT EXISTS source_status (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    source TEXT NOT NULL,
    crawl_time TEXT NOT NULL,
    count INTEGER DEFAULT 0,
    status TEXT NOT NULL,
    error TEXT,
    UNIQUE(date, source)
);

-- 标题变更追踪
CREATE TABLE IF NOT EXISTS title_changes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url_hash TEXT NOT NULL,
    first_seen_date TEXT NOT NULL,
    changed_at TEXT NOT NULL,
    old_title TEXT,
    new_title TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_title_changes_hash ON title_changes(url_hash);
"""


class SQLiteBackend(StorageBackend):
    """基于 SQLite 的本地/NAS 存储后端。"""

    def __init__(self, db_path: str = "data/audit.db"):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_db()

    def _conn(self):
        return sqlite3.connect(self.db_path)

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)
            conn.commit()

    @staticmethod
    def _url_hash(link: str) -> str:
        return hashlib.md5(link.encode("utf-8")).hexdigest() if link else ""

    @staticmethod
    def _now() -> str:
        return datetime.now().isoformat()

    def save_candidates(self, date: str, candidates: List[Dict]) -> None:
        with self._conn() as conn:
            for c in candidates:
                link = c.get("link", "") or ""
                url_hash = self._url_hash(link)
                raw_data = json.dumps(c, ensure_ascii=False)
                try:
                    conn.execute(
                        """
                        INSERT INTO candidates
                        (date, crawl_time, title, summary, link, source, source_type,
                         category, published_date, raw_score, weight, url_hash, raw_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            date,
                            self._now(),
                            c.get("title", ""),
                            c.get("summary", ""),
                            link,
                            c.get("source", ""),
                            c.get("source_type", "rss"),
                            c.get("category", "general"),
                            c.get("date", ""),
                            float(c.get("raw_score", 0) or 0),
                            int(c.get("weight", 5) or 5),
                            url_hash,
                            raw_data,
                        ),
                    )
                except sqlite3.IntegrityError:
                    # URL 重复，跳过
                    pass
            conn.commit()

    def get_candidates(self, date: str) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT raw_data FROM candidates WHERE date = ?", (date,)
            ).fetchall()
        return [json.loads(r[0]) for r in rows]

    def save_screened(self, date: str, screened: List[Dict]) -> None:
        with self._conn() as conn:
            for s in screened:
                conn.execute(
                    """
                    INSERT INTO screened
                    (date, candidate_id, title, source, keep, total_score,
                     dimension_scores, category, reason, audit_mapping_guess)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        date,
                        s.get("candidate_id"),
                        s.get("title", ""),
                        s.get("source", ""),
                        s.get("keep", ""),
                        s.get("total_score"),
                        json.dumps(s.get("dimension_scores", {}), ensure_ascii=False),
                        s.get("category", ""),
                        s.get("reason", ""),
                        s.get("audit_mapping_guess", ""),
                    ),
                )
            conn.commit()

    def get_screened(self, date: str) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT title, source, keep, total_score, dimension_scores,
                       category, reason, audit_mapping_guess
                FROM screened WHERE date = ?
                """,
                (date,),
            ).fetchall()
        result = []
        for r in rows:
            result.append(
                {
                    "title": r[0],
                    "source": r[1],
                    "keep": r[2],
                    "total_score": r[3],
                    "dimension_scores": json.loads(r[4]) if r[4] else {},
                    "category": r[5],
                    "reason": r[6],
                    "audit_mapping_guess": r[7],
                }
            )
        return result

    def save_clusters(self, date: str, clusters: List[Dict]) -> None:
        with self._conn() as conn:
            for c in clusters:
                conn.execute(
                    """
                    INSERT INTO clusters
                    (date, event_title, items, sources, categories, resonance_score, level)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        date,
                        c.get("event_title", ""),
                        json.dumps(c.get("items", []), ensure_ascii=False),
                        json.dumps(c.get("sources", []), ensure_ascii=False),
                        json.dumps(c.get("categories", []), ensure_ascii=False),
                        c.get("resonance_score", 0),
                        c.get("level", ""),
                    ),
                )
            conn.commit()

    def get_clusters(self, date: str) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT event_title, items, sources, categories, resonance_score, level
                FROM clusters WHERE date = ?
                """,
                (date,),
            ).fetchall()
        result = []
        for r in rows:
            result.append(
                {
                    "event_title": r[0],
                    "items": json.loads(r[1]) if r[1] else [],
                    "sources": json.loads(r[2]) if r[2] else [],
                    "categories": json.loads(r[3]) if r[3] else [],
                    "resonance_score": r[4],
                    "level": r[5],
                }
            )
        return result

    def save_report(self, date: str, report: Dict) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO reports
                (date, created_at, top3, summary, html, status)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    date,
                    self._now(),
                    json.dumps(report.get("top3", []), ensure_ascii=False),
                    report.get("summary", ""),
                    report.get("html", ""),
                    report.get("status", "draft"),
                ),
            )
            conn.commit()

    def get_report(self, date: str) -> Optional[Dict]:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT created_at, top3, summary, html, status FROM reports WHERE date = ?",
                (date,),
            ).fetchone()
        if not row:
            return None
        return {
            "date": date,
            "created_at": row[0],
            "top3": json.loads(row[1]) if row[1] else [],
            "summary": row[2],
            "html": row[3],
            "status": row[4],
        }

    def record_push(self, date: str, channel: str, status: str, error: str = "") -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO push_records
                (date, channel, pushed_at, status, error)
                VALUES (?, ?, ?, ?, ?)
                """,
                (date, channel, self._now(), status, error),
            )
            conn.commit()

    def is_pushed(self, date: str, channel: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM push_records
                WHERE date = ? AND channel = ? AND status = 'success'
                """,
                (date, channel),
            ).fetchone()
        return bool(row)

    def record_source_status(
        self,
        date: str,
        source: str,
        count: int,
        status: str,
        error: str = "",
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO source_status
                (date, source, crawl_time, count, status, error)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (date, source, self._now(), count, status, error),
            )
            conn.commit()
