# -*- coding: utf-8 -*-
"""阿里云 FC 函数入口。编排：采集 → 粗筛 → 共振 → 精排 → 生成 → 发送。"""
import json
from datetime import datetime
from typing import Dict, List

import config

from core.fetcher import Fetcher
from core.selector import Selector
from core.resonance import ResonanceDetector
from core.ranker import Ranker
from core.generator import Generator
from core.sender import Sender
from core.storage import SQLiteBackend
from core.skill_loader import load_skill
from core.dedup import dedup_pipeline
from core.papers import looks_like_paper, normalize_paper_candidate, enrich_candidates


# 本地开发用 data/audit.db，FC 生产环境用 NAS 挂载路径
DEFAULT_DB_PATH = config.AUDIT_DB_PATH


def _is_github_repo(item: Dict) -> bool:
    link = item.get("link", "") or ""
    return "github.com" in link and item.get("source_type") == "newsnow"


def _mark_github_repos(candidates: List[Dict], storage, date: str) -> None:
    """标记 GitHub repo 的新增性，并更新 repo_history。"""
    import hashlib

    github_repos = [c for c in candidates if _is_github_repo(c)]
    if not github_repos:
        return

    url_hashes = [hashlib.sha256((c.get("link", "") or "").encode("utf-8")).hexdigest()[:32] for c in github_repos]
    history = storage.get_repo_history(url_hashes)

    new_repo_count = 0
    for c in github_repos:
        url_hash = hashlib.sha256((c.get("link", "") or "").encode("utf-8")).hexdigest()[:32]
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
    fetch_result = fetcher.fetch_with_status()
    candidates = fetch_result["candidates"]
    print(f"   总计候选: {len(candidates)} 条")

    # 记录每个信源状态
    for st in fetch_result.get("sources", []):
        storage.record_source_status(
            today,
            st["name"],
            st["count"],
            st["status"],
            st.get("error", ""),
        )

    # 1.1 论文入库：先把论文类候选存进 papers 表
    paper_candidates = [normalize_paper_candidate(c) for c in candidates if looks_like_paper(c)]
    if paper_candidates:
        storage.save_papers(today, paper_candidates)
        print(f"   论文入库: {len(paper_candidates)} 条")

    storage.save_candidates(today, candidates)

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

    # 1.7 论文摘要富化：如果候选提到库中已有论文，补充 abstract
    enriched_candidates = enrich_candidates(fresh_candidates, storage)
    enriched_count = sum(1 for c in enriched_candidates if c.get("paper_enriched"))
    if enriched_count:
        print(f"   论文摘要富化: {enriched_count} 条")

    # 2. 粗筛（日报 + 深度池分离）
    _skill_log("FILTER", "rss-audit-screener")
    selector = Selector()
    try:
        screened, deep_dive_candidates = selector.screen(enriched_candidates)
    except Exception as e:
        print(f"   [FAIL] 粗筛失败: {e}")
        storage.record_push(today, "daily_pipeline", "failed", f"selector: {e}")
        return _error_response(today, "selector_failed", str(e))
    storage.save_screened(today, screened)
    if deep_dive_candidates:
        storage.save_deep_dive_candidates(today, deep_dive_candidates)
        print(f"   已保存 {len(deep_dive_candidates)} 条到深度挖掘队列")

    # 2.5 内容相似度跨天去重（Jaccard + 可选 AI）
    past_items = storage.get_recent_report_items(days=7)
    use_ai = config.DEDUP_USE_AI
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
    try:
        result = ranker.rank(clusters)
    except Exception as e:
        print(f"   [FAIL] 精排 LLM 失败: {e}")
        storage.record_push(today, "daily_pipeline", "failed", f"ranker: {e}")
        return _error_response(today, "ranker_failed", str(e))
    selected_indices = result.get("selected_indices", [])
    print(f"   Top 8: {len(selected_indices)} 条（前 5 个用于日报）")
    for i, idx in enumerate(selected_indices):
        if idx < len(clusters):
            c = clusters[idx]
            line = c['categories'][0] if c.get('categories') else 'general'
            marker = " [日报]" if i < 5 else ""
            print(f"   • [{line}] {c['event_title']}{marker}")

    # 5. 生成
    _skill_log("GEN", "report-generator")
    generator = Generator()
    try:
        html = generator.generate(selected_indices, clusters)
    except Exception as e:
        print(f"   [FAIL] 生成 LLM 失败: {e}")
        storage.record_push(today, "daily_pipeline", "failed", f"generator: {e}")
        return _error_response(today, "generator_failed", str(e))
    print(f"   HTML 长度: {len(html)} chars")
    storage.save_report(
        today,
        {
            "selected_indices": selected_indices,
            "summary": result.get("summary", ""),
            "html": html,
            "status": "draft",
        },
    )

    # 5.5 记录已报道 URL，用于未来跨天去重（记录全部 8 个 cluster 的 items）
    reported_items = []
    for idx in selected_indices:
        if idx < len(clusters):
            for item in clusters[idx].get("items", []):
                if item.get("link"):
                    reported_items.append(item)
    storage.save_reported_urls(today, reported_items)
    print(f"   已报道 URL 记录: {len(reported_items)} 条（Top 8 全部记录）")

    # 6. 发送
    print("\n[MAIL] 6. 发送邮件...")
    channel = "email"
    if storage.is_pushed(today, channel):
        print(f"   [SKIP] 今日 {channel} 已推送过")
    else:
        sender = Sender()
        try:
            sender.send(html, subject="IT 监管日报")
            storage.record_push(today, channel, "success")
            print("   [OK] 发送成功")
        except Exception as e:
            storage.record_push(today, channel, "failed", str(e))
            print(f"   [FAIL] 发送失败: {e}")
            return _error_response(today, "send_failed", str(e))

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
            "top8": len(selected_indices),
        }, ensure_ascii=False),
    }


def _error_response(date: str, stage: str, error: str) -> Dict:
    """记录失败并返回统一错误响应。"""
    return {
        "statusCode": 500,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "date": date,
            "stage": stage,
            "error": error,
        }, ensure_ascii=False),
    }


def local_run():
    """本地测试入口：python index.py"""
    handler({}, None)


if __name__ == "__main__":
    local_run()
