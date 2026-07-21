# -*- coding: utf-8 -*-
"""集中配置管理。所有密钥从环境变量读取，适配阿里云 FC 与本地测试。"""
import os
from datetime import datetime, timedelta, timezone


# 业务统一使用北京时间（UTC+8，naive）：FC 容器系统时钟是 UTC，
# 若直接用 datetime.now()，北京早上 7 点的运行会被记到前一天的日期键下
BJ_TZ = timezone(timedelta(hours=8))


def now_bj() -> datetime:
    """返回北京时间的 naive datetime，替代所有 datetime.now() 调用点。"""
    return datetime.now(BJ_TZ).replace(tzinfo=None)


def _bool_env(key: str, default: bool = False) -> bool:
    """安全解析布尔型环境变量。"""
    return os.getenv(key, str(default).lower()).lower() in ("1", "true", "yes", "on")


# ── 多模型供应商配置 ──
# 文档解析/筛选/生成任务：走第三方官方 API（deepseek / moonshot）
# STT 等百炼特色任务：走 dashscope（百炼）
# GLM 保留代码但暂不使用
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "deepseek").lower()

# ── Chat/Completions 官方 API Key ──
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
MOONSHOT_API_KEY = os.getenv("MOONSHOT_API_KEY", "")

# ── 百炼 API Key（用于 STT 等非 chat 任务）──
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")

# ── 智谱 API Key（保留，暂不启用）──
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")

# ── 各供应商 Base URL ──
DEEPSEEK_BASE_URL = os.getenv(
    "DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"
)
MOONSHOT_BASE_URL = os.getenv(
    "MOONSHOT_BASE_URL", "https://api.moonshot.cn/v1"
)
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)
ZHIPU_BASE_URL = os.getenv(
    "ZHIPU_BASE_URL", "https://open.bigmodel.cn/api/paas/v4"
)

# 模型名称（默认走 DeepSeek 官方）
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-v4-flash")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.3"))
MODEL_MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", "8192"))

# 模型路由：不同任务可用不同模型
# 格式：provider:model_name，如 "deepseek:deepseek-v4-pro" / "moonshot:kimi-k2-6"
# 也支持简写：只写模型名（如 "deepseek-v4-pro"），自动推断供应商
MODEL_SCREEN = os.getenv("MODEL_SCREEN", "")       # 粗筛，空则 fallback 到 MODEL_NAME
MODEL_RANK = os.getenv("MODEL_RANK", "")           # 精排，空则 fallback
MODEL_GENERATE = os.getenv("MODEL_GENERATE", "")   # 生成，空则 fallback
MODEL_DEDUP = os.getenv("MODEL_DEDUP", "")         # 去重，空则 fallback
MODEL_RESONANCE = os.getenv("MODEL_RESONANCE", "deepseek-v4-pro")   # 共振精评，默认 DeepSeek V4 Pro

# DeepSeek V4 思考模式控制：默认不开启（disabled），可设为 high/max 开启
DEEPSEEK_REASONING_EFFORT = os.getenv("DEEPSEEK_REASONING_EFFORT", "").lower()

# ── 采集 ──
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "12"))
NVD_RESULTS_PER_PAGE = int(os.getenv("NVD_RESULTS_PER_PAGE", "10"))
RSS_MAX_ITEMS = int(os.getenv("RSS_MAX_ITEMS", "20"))

# ── 测试模式 ──
# IS_TEST=yes 时：绕过"每日一发"限制、跳过 reported_urls 写入（保护次日去重）、
# 推送记录写入 email_test 渠道、邮件主题加 [TEST] 前缀。其余环节与正式运行一致。
IS_TEST = _bool_env("IS_TEST", False)

# ── 邮件 ──
# 注意：阿里云 ECS/FC 默认封禁出方向 25 端口，MAIL_PORT 请用 465（SSL）
MAIL_HOST = os.getenv("MAIL_HOST", "")
MAIL_PORT = int(os.getenv("MAIL_PORT", "465"))
MAIL_USER = os.getenv("MAIL_USER", "")
MAIL_PASS = os.getenv("MAIL_PASS", "")
MAIL_TO_LIST = [m.strip() for m in os.getenv("MAIL_TO_LIST", "").split(",") if m.strip()]
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USER)

# ── 存储 ──
# 本地开发：默认 data/audit.db；FC 生产环境：通过环境变量指向 NAS 路径
AUDIT_DB_PATH = os.getenv("AUDIT_DB_PATH", "data/audit.db")

# ── 路径 ──
SOURCES_PATH = os.path.join(os.path.dirname(__file__), "sources.json")

# ── 调试 ──
DEBUG = _bool_env("DEBUG", False)
DEDUP_USE_AI = _bool_env("DEDUP_USE_AI", False)
# 共振层 LLM 精评开关：开启后多源事件簇走 cross-source-resonance skill，关闭走本地规则
RESONANCE_USE_AI = _bool_env("RESONANCE_USE_AI", False)
