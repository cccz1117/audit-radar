# -*- coding: utf-8 -*-
"""阿里云 FC 函数入口。编排：采集 → 粗筛 → 共振 → 精排 → 生成 → 发送。"""
import json
import os
from datetime import datetime

from core.fetcher import Fetcher
from core.selector import Selector
from core.resonance import ResonanceDetector
from core.ranker import Ranker
from core.generator import Generator
from core.sender import Sender
from core.storage import SQLiteBackend


# 本地开发用 data/audit.db，FC 生产环境用 NAS 挂载路径
DEFAULT_DB_PATH = os.getenv("AUDIT_DB_PATH", "data/audit.db")


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

    # 2. 粗筛
    print("\n[FILTER] 2. 粗筛（rss-audit-screener）...")
    selector = Selector()
    screened = selector.screen(candidates)
    print(f"   保留: {len(screened)} 条")
    storage.save_screened(today, screened)

    # 3. 共振
    print("\n[RESONANCE] 3. 多源共振检测...")
    detector = ResonanceDetector()
    clusters = detector.detect(screened)
    print(f"   事件簇: {len(clusters)} 个")
    for c in clusters[:5]:
        print(f"   • {c['event_title'][:50]}... | 共振:{c['resonance_score']} | 等级:{c['level']}")
    storage.save_clusters(today, clusters)

    # 4. 精排
    print("\n[RANK] 4. 精排（audit-news-ranker）...")
    ranker = Ranker()
    result = ranker.rank(clusters)
    top3 = result.get("top3", [])
    print(f"   Top 3: {len(top3)} 条")
    for t in top3:
        print(f"   • [{t.get('line','')}] {t.get('title','')}")

    # 5. 生成
    print("\n[GEN] 5. 生成日报...")
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
            "screened": len(screened),
            "clusters": len(clusters),
            "top3": len(top3),
        }, ensure_ascii=False),
    }


def local_run():
    """本地测试入口：python index.py"""
    handler({}, None)


if __name__ == "__main__":
    local_run()
