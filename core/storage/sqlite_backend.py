# -*- coding: utf-8 -*-
"""SQLite 存储后端实现。"""
import hashlib
import json
import os
import re
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

-- 已报道 URL（用于跨天去重）
CREATE TABLE IF NOT EXISTS reported_urls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    url_hash TEXT NOT NULL,
    title TEXT,
    summary TEXT,
    UNIQUE(date, url_hash)
);
CREATE INDEX IF NOT EXISTS idx_reported_urls_hash ON reported_urls(url_hash);

-- GitHub repo 历史（用于判断是否为新增 repo）
CREATE TABLE IF NOT EXISTS repo_history (
    url_hash TEXT PRIMARY KEY,
    repo_name TEXT,
    first_seen_date TEXT NOT NULL,
    last_seen_date TEXT NOT NULL,
    max_stars INTEGER DEFAULT 0
);

-- 深度挖掘候选池（播客/长博客等，用于周报/月报）
CREATE TABLE IF NOT EXISTS deep_dive_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    url_hash TEXT UNIQUE,
    title TEXT NOT NULL,
    source TEXT NOT NULL,
    summary TEXT,
    link TEXT,
    report_cycle TEXT NOT NULL DEFAULT 'weekly',
    content_type TEXT NOT NULL DEFAULT 'podcast',
    audio_url TEXT,
    status TEXT NOT NULL DEFAULT 'pending',
    reason TEXT,
    audit_mapping_guess TEXT,
    metadata TEXT,
    week_id TEXT,
    created_at TEXT NOT NULL,
    processed_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_deep_dive_date ON deep_dive_queue(date);
CREATE INDEX IF NOT EXISTS idx_deep_dive_status ON deep_dive_queue(status);
CREATE INDEX IF NOT EXISTS idx_deep_dive_cycle ON deep_dive_queue(report_cycle);
CREATE INDEX IF NOT EXISTS idx_deep_dive_week ON deep_dive_queue(week_id);

-- 周报
CREATE TABLE IF NOT EXISTS weekly_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    week_id TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL,
    topics TEXT NOT NULL,
    html TEXT NOT NULL,
    status TEXT DEFAULT 'draft'
);

-- 论文库（用于跨天追踪论文，供后续引用时补全摘要）
CREATE TABLE IF NOT EXISTS papers (
    url_hash TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    authors TEXT,
    abstract TEXT,
    link TEXT NOT NULL,
    source TEXT,
    first_seen_date TEXT NOT NULL,
    last_seen_date TEXT NOT NULL,
    metadata TEXT
);
CREATE INDEX IF NOT EXISTS idx_papers_title ON papers(title);
CREATE INDEX IF NOT EXISTS idx_papers_date ON papers(first_seen_date);

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
            # 兼容旧库：为 reported_urls 增加 summary 字段
            try:
                conn.execute("ALTER TABLE reported_urls ADD COLUMN IF NOT EXISTS summary TEXT")
                conn.commit()
            except sqlite3.OperationalError:
                pass

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

    def save_reported_urls(self, date: str, items: List[Dict]) -> None:
        """保存某日最终入选报道的 URL 和摘要。"""
        with self._conn() as conn:
            for item in items:
                link = item.get("link", "") or ""
                if not link:
                    continue
                url_hash = self._url_hash(link)
                try:
                    conn.execute(
                        """
                        INSERT INTO reported_urls (date, url_hash, title, summary)
                        VALUES (?, ?, ?, ?)
                        ON CONFLICT(date, url_hash) DO UPDATE SET
                            title = excluded.title,
                            summary = COALESCE(excluded.summary, reported_urls.summary)
                        """,
                        (date, url_hash, item.get("title", ""), item.get("summary", "")),
                    )
                except sqlite3.OperationalError:
                    # 旧库无 summary 字段时的兼容：仅插入 date/url_hash/title
                    try:
                        conn.execute(
                            "INSERT INTO reported_urls (date, url_hash, title) VALUES (?, ?, ?)",
                            (date, url_hash, item.get("title", "")),
                        )
                    except sqlite3.IntegrityError:
                        pass
                except sqlite3.IntegrityError:
                    pass
            conn.commit()

    def is_recently_reported(self, url_hash: str, days: int = 7) -> bool:
        """查询 URL 最近 N 天是否已被报道。"""
        if not url_hash:
            return False
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT 1 FROM reported_urls
                WHERE url_hash = ? AND date >= ?
                """,
                (url_hash, cutoff),
            ).fetchone()
        return bool(row)

    def get_recent_report_items(self, days: int = 7) -> List[Dict]:
        """获取最近 N 天已报道的新闻标题和摘要，用于内容相似度去重。"""
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT date, url_hash, title, summary FROM reported_urls
                WHERE date >= ?
                ORDER BY date DESC
                """,
                (cutoff,),
            ).fetchall()

        return [
            {
                "date": date,
                "title": title or "",
                "summary": summary or "",
                "url_hash": url_hash or "",
            }
            for date, url_hash, title, summary in rows
        ]

    def get_repo_history(self, url_hashes: List[str]) -> Dict[str, Dict]:
        """批量查询 repo 历史。返回 {url_hash: {...}}。"""
        if not url_hashes:
            return {}
        placeholders = ",".join("?" * len(url_hashes))
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT url_hash, repo_name, first_seen_date, last_seen_date, max_stars
                FROM repo_history
                WHERE url_hash IN ({placeholders})
                """,
                tuple(url_hashes),
            ).fetchall()
        return {
            r[0]: {
                "repo_name": r[1],
                "first_seen_date": r[2],
                "last_seen_date": r[3],
                "max_stars": r[4],
            }
            for r in rows
        }

    def update_repo_history(self, date: str, repos: List[Dict]) -> None:
        """更新 GitHub repo 历史。新增 repo 插入，已存在则更新最后出现时间和最大 star。"""
        with self._conn() as conn:
            for repo in repos:
                url_hash = self._url_hash(repo.get("link", ""))
                if not url_hash:
                    continue
                repo_name = repo.get("title", "")
                stars = int(repo.get("stars", 0) or 0)
                conn.execute(
                    """
                    INSERT INTO repo_history (url_hash, repo_name, first_seen_date, last_seen_date, max_stars)
                    VALUES (?, ?, ?, ?, ?)
                    ON CONFLICT(url_hash) DO UPDATE SET
                        last_seen_date = excluded.last_seen_date,
                        max_stars = MAX(repo_history.max_stars, excluded.max_stars)
                    """,
                    (url_hash, repo_name, date, date, stars),
                )
            conn.commit()

    def save_deep_dive_candidates(self, date: str, candidates: List[Dict]) -> None:
        """保存深度挖掘候选。相同 URL 不重复插入。"""
        with self._conn() as conn:
            for c in candidates:
                link = c.get("link", "") or ""
                url_hash = self._url_hash(link)
                if not url_hash:
                    continue
                try:
                    conn.execute(
                        """
                        INSERT INTO deep_dive_queue
                        (date, url_hash, title, source, summary, link, report_cycle,
                         content_type, audio_url, status, reason, audit_mapping_guess,
                         metadata, created_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(url_hash) DO NOTHING
                        """,
                        (
                            date,
                            url_hash,
                            c.get("title", ""),
                            c.get("source", ""),
                            c.get("summary", ""),
                            link,
                            c.get("report_cycle", "weekly"),
                            c.get("content_type", "podcast"),
                            c.get("audio_url", ""),
                            c.get("status", "pending"),
                            c.get("deep_dive_reason", ""),
                            c.get("audit_mapping_guess", ""),
                            json.dumps(c.get("metadata", {}), ensure_ascii=False),
                            self._now(),
                        ),
                    )
                except sqlite3.IntegrityError:
                    pass
            conn.commit()

    def get_deep_dive_candidates(
        self,
        report_cycle: str = "weekly",
        week_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict]:
        """读取深度挖掘候选。"""
        conditions = ["report_cycle = ?"]
        params: List[Optional[str]] = [report_cycle]
        if status:
            conditions.append("status = ?")
            params.append(status)
        else:
            conditions.append("status IN ('pending', 'processed')")
        if week_id:
            conditions.append("week_id = ?")
            params.append(week_id)

        where_clause = " AND ".join(conditions)
        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT date, url_hash, title, source, summary, link, report_cycle,
                       content_type, audio_url, status, reason, audit_mapping_guess,
                       metadata, week_id
                FROM deep_dive_queue
                WHERE {where_clause}
                ORDER BY date DESC, source
                """,
                tuple(params),
            ).fetchall()
        result = []
        for r in rows:
            result.append({
                "date": r[0],
                "url_hash": r[1],
                "title": r[2],
                "source": r[3],
                "summary": r[4],
                "link": r[5],
                "report_cycle": r[6],
                "content_type": r[7],
                "audio_url": r[8],
                "status": r[9],
                "deep_dive_reason": r[10],
                "audit_mapping_guess": r[11],
                "metadata": json.loads(r[12]) if r[12] else {},
                "week_id": r[13],
            })
        return result

    def update_deep_dive_status(
        self,
        url_hashes: List[str],
        status: str,
        week_id: Optional[str] = None,
    ) -> None:
        """批量更新深度挖掘候选状态。"""
        if not url_hashes:
            return
        placeholders = ",".join("?" * len(url_hashes))
        params: List[Optional[str]] = [status, self._now()]
        if week_id:
            params.append(week_id)
        params.extend(url_hashes)
        set_week = ", week_id = ?" if week_id else ""
        with self._conn() as conn:
            conn.execute(
                f"""
                UPDATE deep_dive_queue
                SET status = ?, processed_at = ?{set_week}
                WHERE url_hash IN ({placeholders})
                """,
                tuple(params),
            )
            conn.commit()

    def save_weekly_report(self, week_id: str, report: Dict) -> None:
        """保存周报。"""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO weekly_reports
                (week_id, created_at, topics, html, status)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    week_id,
                    self._now(),
                    json.dumps(report.get("topics", []), ensure_ascii=False),
                    report.get("html", ""),
                    report.get("status", "draft"),
                ),
            )
            conn.commit()

    def get_weekly_report(self, week_id: str) -> Optional[Dict]:
        """读取周报。"""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT created_at, topics, html, status FROM weekly_reports WHERE week_id = ?",
                (week_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "week_id": week_id,
            "created_at": row[0],
            "topics": json.loads(row[1]) if row[1] else [],
            "html": row[2],
            "status": row[3],
        }

    def save_papers(self, date: str, candidates: List[Dict]) -> None:
        """保存论文候选到论文库。"""
        with self._conn() as conn:
            for c in candidates:
                link = c.get("link", "") or ""
                if not link:
                    continue
                url_hash = self._url_hash(link)
                title = c.get("title", "")
                # 只保存看起来是论文的条目
                if not self._looks_like_paper(link, title, c.get("source", "")):
                    continue
                abstract = c.get("summary", "") or c.get("abstract", "")
                authors = c.get("authors", "")
                metadata = json.dumps(c.get("metadata", {}), ensure_ascii=False)
                conn.execute(
                    """
                    INSERT INTO papers
                    (url_hash, title, authors, abstract, link, source,
                     first_seen_date, last_seen_date, metadata)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(url_hash) DO UPDATE SET
                        last_seen_date = excluded.last_seen_date,
                        abstract = COALESCE(excluded.abstract, papers.abstract),
                        title = excluded.title
                    """,
                    (url_hash, title, authors, abstract, link,
                     c.get("source", ""), date, date, metadata),
                )
            conn.commit()

    @staticmethod
    def _looks_like_paper(link: str, title: str, source: str) -> bool:
        """判断是否为论文条目。"""
        link_l = link.lower()
        title_l = title.lower()
        source_l = source.lower()
        if "arxiv.org" in link_l:
            return True
        if "huggingface.co/papers" in link_l:
            return True
        if "paperswithcode.com" in link_l:
            return True
        if "arxiv" in source_l or "huggingface papers" in source_l:
            return True
        # 标题含 arXiv ID，如 arXiv:2401.12345
        if re.search(r"arxiv\s*[:\-]?\s*\d{4}\.\d+", title_l):
            return True
        return False

    def get_paper_by_link(self, link: str) -> Optional[Dict]:
        """通过链接查询论文。"""
        url_hash = self._url_hash(link)
        with self._conn() as conn:
            row = conn.execute(
                """
                SELECT title, authors, abstract, link, source, first_seen_date, metadata
                FROM papers WHERE url_hash = ?
                """,
                (url_hash,),
            ).fetchone()
        if not row:
            return None
        return {
            "title": row[0],
            "authors": row[1],
            "abstract": row[2],
            "link": row[3],
            "source": row[4],
            "first_seen_date": row[5],
            "metadata": json.loads(row[6]) if row[6] else {},
        }

    def search_papers_by_title(self, title: str, days: int = 30) -> List[Dict]:
        """按标题关键词搜索最近 N 天的论文（关键词之间是 AND 关系）。"""
        from datetime import datetime, timedelta

        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        keywords = [k.strip() for k in title.lower().split() if len(k.strip()) >= 2]
        if not keywords:
            return []

        conditions = " AND ".join(["LOWER(title) LIKE ?"] * len(keywords))
        params = [f"%{k}%" for k in keywords]
        params.append(cutoff)

        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT title, authors, abstract, link, source, first_seen_date, metadata
                FROM papers
                WHERE {conditions} AND first_seen_date >= ?
                ORDER BY first_seen_date DESC
                LIMIT 5
                """,
                tuple(params),
            ).fetchall()
        return [
            {
                "title": r[0],
                "authors": r[1],
                "abstract": r[2],
                "link": r[3],
                "source": r[4],
                "first_seen_date": r[5],
                "metadata": json.loads(r[6]) if r[6] else {},
            }
            for r in rows
        ]
