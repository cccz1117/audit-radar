# -*- coding: utf-8 -*-
"""阿里云 FC 函数入口。编排：采集 → 粗筛 → 共振 → 精排 → 生成 → 发送。"""
import json
import os
from datetime import datetime
from typing import Dict, List

from core.fetcher import Fetcher
from core.selector import Selector
from core.resonance import ResonanceDetector
from core.ranker import Ranker
from core.generator import Generator
from core.sender import Sender
from core.storage import SQLiteBackend
from core.skill_loader import load_skill
from core.dedup import dedup_pipeline


# 本地开发用 data/audit.db，FC 生产环境用 NAS 挂载路径
DEFAULT_DB_PATH = os.getenv("AUDIT_DB_PATH", "data/audit.db")


def _is_github_repo(item: Dict) -> bool:
    link = item.get("link", "") or ""
    return "github.com" in link and item.get("source_type") == "newsnow"


def _mark_github_repos(candidates: List[Dict], storage, date: str) -> None:
    """标记 GitHub repo 的新增性，并更新 repo_history。"""
    import hashlib

    github_repos = [c for c in candidates if _is_github_repo(c)]
    if not github_repos:
        return

    url_hashes = [hashlib.md5((c.get("link", "") or "").encode("utf-8")).hexdigest() for c in github_repos]
    history = storage.get_repo_history(url_hashes)

    new_repo_count = 0
    for c in github_repos:
        url_hash = hashlib.md5((c.get("link", "") or "").encode("utf-8")).hexdigest()
        is_new = url_hash not in history
        c["is_new_repo"] = is_new
        c["repo_stars"] = int(c.get("stars", 0) or 0)
        if is_new:
            new_repo_count += 1

    storage.update_repo_history(date, github_repos)
    print(f"   GitHub repos: {len(github_repos)} 个，新增: {new_repo_count} 个")


def _skill_log(step: str, skill_name: str) -> None:
    """从 skill metadata 读取信息并打印日志。"""
    try:
        meta = load_skill(skill_name)
        print(f"\n[{step}] {meta['name']}")
        print(f"   {meta['description']}")
        print(f"   entrypoint: {meta['entrypoint']}")
    except Exception:
        # 如果 skill 加载失败，兜底打印
        print(f"\n[{step}] {skill_name}")


def handler(event, context):
    """阿里云 FC HTTP 触发 / 定时触发入口。"""
    today = datetime.now().strftime("%Y-%m-%d")
    storage = SQLiteBackend(db_path=DEFAULT_DB_PATH)

    print("=" * 50)
    print("Audit Radar 开始运行")
    print(f"日期: {today} | 数据库: {DEFAULT_DB_PATH}")
    print("=" * 50)

    # 1. 采集
    print("\n[NET] 1. 采集信源...")
    fetcher = Fetcher()
    candidates = fetcher.fetch_all()
    print(f"   总计候选: {len(candidates)} 条")
    storage.save_candidates(today, candidates)
    storage.record_source_status(today, "all", len(candidates), "success")

    # 1.5 URL 跨天去重（粗筛）
    url_dedup_result = dedup_pipeline(
        candidates, [],
        lambda h: storage.is_recently_reported(h, days=7),
        [],
        use_ai=False,
    )
    fresh_candidates = url_dedup_result["url_kept"]
    url_filtered = url_dedup_result["url_filtered"]
    print(f"   URL 去重过滤: {len(url_filtered)} 条，剩余: {len(fresh_candidates)} 条")

    # 1.6 标记 GitHub repo 新增性
    _mark_github_repos(fresh_candidates, storage, today)

    # 2. 粗筛（日报 + 深度池分离）
    _skill_log("FILTER", "rss-audit-screener")
    selector = Selector()
    screened, deep_dive_candidates = selector.screen(fresh_candidates)
    print(f"   日报保留: {len(screened)} 条 | 深度池候选: {len(deep_dive_candidates)} 条")
    storage.save_screened(today, screened)
    if deep_dive_candidates:
        storage.save_deep_dive_candidates(today, deep_dive_candidates)
        print(f"   已保存 {len(deep_dive_candidates)} 条到深度挖掘队列")

    # 2.5 内容相似度跨天去重（Jaccard + 可选 AI）
    past_items = storage.get_recent_report_items(days=7)
    use_ai = os.getenv("DEDUP_USE_AI", "false").lower() in ("1", "true", "yes")
    dedup_result = dedup_pipeline(
        [], screened,
        lambda h: False,
        past_items,
        use_ai=use_ai,
    )
    deduped_screened = dedup_result["final_kept"]
    print(f"   Jaccard 过滤: {len(dedup_result['jaccard_filtered'])} 条")
    if use_ai:
        print(f"   AI 批量判断保留: {len(dedup_result['ai_kept'])} 条")
    else:
        print(f"   AI 未启用，Jaccard 后保留: {len(dedup_result['jaccard_kept'])} 条")
    print(f"   去重后剩余: {len(deduped_screened)} 条")

    # 3. 共振
    print("\n[RESONANCE] 3. 多源共振检测...")
    detector = ResonanceDetector()
    clusters = detector.detect(deduped_screened)
    print(f"   事件簇: {len(clusters)} 个")
    for c in clusters[:5]:
        print(f"   • {c['event_title'][:50]}... | 共振:{c['resonance_score']} | 等级:{c['level']}")
    storage.save_clusters(today, clusters)

    # 4. 精排
    _skill_log("RANK", "audit-news-ranker")
    ranker = Ranker()
    result = ranker.rank(clusters)
    top3 = result.get("top3", [])
    print(f"   Top 3: {len(top3)} 条")
    for t in top3:
        print(f"   • [{t.get('line','')}] {t.get('title','')}")

    # 5. 生成
    _skill_log("GEN", "report-generator")
    generator = Generator()
    html = generator.generate(top3, clusters)
    print(f"   HTML 长度: {len(html)} chars")
    storage.save_report(
        today,
        {
            "top3": top3,
            "summary": result.get("summary", ""),
            "html": html,
            "status": "draft",
        },
    )

    # 5.5 记录已报道 URL，用于未来跨天去重
    reported_items = []
    for t in top3:
        # 从 clusters 中找到对应原始条目，提取 link
        for c in clusters:
            if c["event_title"] == t.get("title") or t.get("title", "") in c["event_title"]:
                for item in c.get("items", []):
                    if item.get("link"):
                        reported_items.append(item)
                break
    storage.save_reported_urls(today, reported_items)
    print(f"   已报道 URL 记录: {len(reported_items)} 条")

    # 6. 发送
    print("\n[MAIL] 6. 发送邮件...")
    channel = "email"
    if storage.is_pushed(today, channel):
        print(f"   [SKIP] 今日 {channel} 已推送过")
    else:
        sender = Sender()
        try:
            sender.send(html, subject="AI审计智能日报")
            storage.record_push(today, channel, "success")
            print("   [OK] 发送成功")
        except Exception as e:
            storage.record_push(today, channel, "failed", str(e))
            print(f"   [FAIL] 发送失败: {e}")
            raise

    print("\n[OK] Audit Radar 完成")
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "total_candidates": len(candidates),
            "url_filtered": len(url_filtered),
            "fresh_candidates": len(fresh_candidates),
            "screened": len(screened),
            "deep_dive_candidates": len(deep_dive_candidates),
            "deduped_screened": len(deduped_screened),
            "clusters": len(clusters),
            "top3": len(top3),
        }, ensure_ascii=False),
    }


def local_run():
    """本地测试入口：python index.py"""
    handler({}, None)


if __name__ == "__main__":
    local_run()
