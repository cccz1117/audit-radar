# -*- coding: utf-8 -*-
"""阿里云 FC 函数入口。编排：采集 → 粗筛 → 共振 → 精排 → 生成 → 发送。"""
import json

from core.fetcher import Fetcher
from core.selector import Selector
from core.resonance import ResonanceDetector
from core.ranker import Ranker
from core.generator import Generator
from core.sender import Sender


def handler(event, context):
    """阿里云 FC HTTP 触发 / 定时触发入口。"""
    print("=" * 50)
    print("Audit Radar 开始运行")
    print("=" * 50)

    # 1. 采集
    print("\n📡 1. 采集信源...")
    fetcher = Fetcher()
    candidates = fetcher.fetch_all()
    print(f"   总计候选: {len(candidates)} 条")

    # 2. 粗筛
    print("\n🧹 2. 粗筛（rss-audit-screener）...")
    selector = Selector()
    screened = selector.screen(candidates)

    # 3. 共振
    print("\n🌐 3. 多源共振检测...")
    detector = ResonanceDetector()
    clusters = detector.detect(screened)
    print(f"   事件簇: {len(clusters)} 个")
    for c in clusters[:5]:
        print(f"   • {c['event_title'][:50]}... | 共振:{c['resonance_score']} | 等级:{c['level']}")

    # 4. 精排
    print("\n📊 4. 精排（audit-news-ranker）...")
    ranker = Ranker()
    result = ranker.rank(clusters)
    top3 = result.get("top3", [])
    print(f"   Top 3: {len(top3)} 条")
    for t in top3:
        print(f"   • [{t.get('line','')}] {t.get('title','')}")

    # 5. 生成
    print("\n📝 5. 生成日报...")
    generator = Generator()
    html = generator.generate(top3, clusters)
    print(f"   HTML 长度: {len(html)} chars")

    # 6. 发送
    print("\n📧 6. 发送邮件...")
    sender = Sender()
    sender.send(html, subject="AI审计智能日报")

    print("\n✅ Audit Radar 完成")
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
