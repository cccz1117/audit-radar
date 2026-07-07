# -*- coding: utf-8 -*-
"""周报入口：每周六运行，读取 deep_dive_queue，生成并发送周报。

本脚本默认在阿里云函数计算（FC）上由定时触发器调用，也可本地测试：
    python weekly.py
"""
import json
from datetime import datetime, timedelta
from typing import Dict

from core.storage import SQLiteBackend

import config
from core.weekly_generator import WeeklyGenerator
from core.sender import Sender
from core.skill_loader import load_skill


DEFAULT_DB_PATH = config.AUDIT_DB_PATH


def _iso_week_id(d: datetime = None) -> str:
    """生成 ISO 周标识，例如 2026-W27。"""
    if d is None:
        d = datetime.now()
    year, week, _ = d.isocalendar()
    return f"{year}-W{week:02d}"


def _week_bounds(week_id: str):
    """根据 week_id 返回当周起止日期（周一 00:00 到周日 23:59）。"""
    year, week = week_id.split("-W")
    year = int(year)
    week = int(week)
    # ISO 周是从周一开始的
    monday = datetime.fromisocalendar(year, week, 1)
    sunday = monday + timedelta(days=6, hours=23, minutes=59, seconds=59)
    return monday, sunday


def _skill_log(step: str, skill_name: str) -> None:
    """从 skill metadata 读取信息并打印日志。"""
    try:
        meta = load_skill(skill_name)
        print(f"\n[{step}] {meta['name']}")
        print(f"   {meta['description']}")
        print(f"   entrypoint: {meta['entrypoint']}")
    except Exception:
        print(f"\n[{step}] {skill_name}")


def _transcribe_audio_pseudocode(audio_url: str) -> str:
    """
    [PSEUDOCODE] 音频转录占位函数。

    当前策略：不主动转录。后续接入阿里云语音服务时，按以下步骤实现：

    1. 下载音频文件到临时目录（FC 临时磁盘 /tmp）。
    2. 调用阿里云智能语音交互（nls）或 DashScope 语音转文字 API：
       - 长音频：使用录音文件识别（一句话识别/录音文件识别极速版）。
       - 短音频：使用实时语音识别。
    3. 对转录文本做说话人分离（diarization）和章节对齐。
    4. 仅保留被周报选中的主题对应的音频才执行转录，避免每日全量 transcribe。
    5. 转录结果存入 deep_dive_queue.metadata.transcript，供后续周报生成使用。

    参数：
        audio_url: 播客音频直链（如 .mp3 / .m4a）
    返回：
        str: 转录文本（当前返回空字符串）
    """
    # TODO: implement when audio transcription is enabled
    # Example (pseudo):
    #   client = AliyunNlsClient()
    #   task_id = client.submit_task(audio_url)
    #   transcript = client.wait_for_result(task_id)
    #   return transcript
    return ""


def handler(event, context):
    """阿里云 FC HTTP/定时触发入口。"""
    today = datetime.now()
    week_id = _iso_week_id(today)
    storage = SQLiteBackend(db_path=DEFAULT_DB_PATH)

    print("=" * 50)
    print("Audit Radar Weekly Report 开始运行")
    print(f"周次: {week_id} | 数据库: {DEFAULT_DB_PATH}")
    print("=" * 50)

    # 1. 读取本周深度挖掘候选
    print("\n[QUEUE] 1. 读取本周深度挖掘队列...")
    monday, sunday = _week_bounds(week_id)
    # 取 pending 和已 processed 但未绑定到本周的候选
    candidates = storage.get_deep_dive_candidates(
        report_cycle="weekly",
        status="pending",
    )
    # 过滤到只保留本周内的（按 date 字段）
    week_candidates = [
        c for c in candidates
        if monday.strftime("%Y-%m-%d") <= c.get("date", "") <= sunday.strftime("%Y-%m-%d")
    ]
    print(f"   本周候选: {len(week_candidates)} 条")

    if not week_candidates:
        print("   [SKIP] 本周无候选，不生成周报")
        return {
            "statusCode": 200,
            "body": json.dumps({"week_id": week_id, "topics": 0, "status": "skipped"}),
        }

    # 2. [PSEUDOCODE] 音频转录（当前不执行）
    print("\n[AUDIO] 2. 音频转录（当前跳过，仅保留接口）...")
    for c in week_candidates:
        if c.get("audio_url"):
            # 当前返回空字符串；后续 uncomment 启用
            _ = _transcribe_audio_pseudocode(c["audio_url"])
    print("   [SKIP] 转录未启用")

    # 3. 生成周报
    _skill_log("GEN", "weekly-report-generator")
    generator = WeeklyGenerator()
    try:
        result = generator.generate(week_candidates, week_id)
    except Exception as e:
        print(f"   [FAIL] 周报生成 LLM 失败: {e}")
        return _error_response(week_id, "weekly_generator_failed", str(e))
    html = result.get("html", "")
    topics = result.get("topics", [])
    print(f"   生成主题: {len(topics)} 个 | HTML 长度: {len(html)} chars")

    storage.save_weekly_report(
        week_id,
        {
            "topics": topics,
            "html": html,
            "status": "draft",
        },
    )

    # 4. 标记已处理
    processed_hashes = [c.get("url_hash", "") for c in week_candidates if c.get("url_hash")]
    if processed_hashes:
        storage.update_deep_dive_status(processed_hashes, "processed", week_id=week_id)
        print(f"   已标记处理: {len(processed_hashes)} 条")

    # 5. 发送邮件
    print("\n[MAIL] 4. 发送周报邮件...")
    channel = "email"
    sent = False
    if storage.is_pushed(week_id, channel):
        print(f"   [SKIP] 本周 {channel} 已推送过")
    else:
        sender = Sender()
        try:
            sender.send(html, subject=f"AI审计情报周报 · {week_id}")
            storage.record_push(week_id, channel, "success")
            sent = True
            print("   [OK] 发送成功")
        except Exception as e:
            storage.record_push(week_id, channel, "failed", str(e))
            print(f"   [FAIL] 发送失败: {e}")
            raise

    print("\n[OK] Audit Radar Weekly Report 完成")
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(
            {
                "week_id": week_id,
                "candidates": len(week_candidates),
                "topics": len(topics),
                "status": "sent" if sent else "draft",
            },
            ensure_ascii=False,
        ),
    }


def _error_response(week_id: str, stage: str, error: str) -> Dict:
    """返回统一错误响应。"""
    return {
        "statusCode": 500,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "week_id": week_id,
            "stage": stage,
            "error": error,
        }, ensure_ascii=False),
    }


def local_run():
    """本地测试入口：python weekly.py"""
    handler({}, None)


if __name__ == "__main__":
    local_run()
