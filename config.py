# -*- coding: utf-8 -*-
"""集中配置管理。所有密钥从环境变量读取，适配阿里云 FC 与本地测试。"""
import os


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
# 格式：provider:model_name，如 "deepseek:ds-v4-pro" / "moonshot:kimi-k2-6"
# 也支持简写：只写模型名（如 "ds-v4-pro"），自动推断供应商
MODEL_SCREEN = os.getenv("MODEL_SCREEN", "")       # 粗筛，空则 fallback 到 MODEL_NAME
MODEL_RANK = os.getenv("MODEL_RANK", "")           # 精排，空则 fallback
MODEL_GENERATE = os.getenv("MODEL_GENERATE", "")   # 生成，空则 fallback
MODEL_DEDUP = os.getenv("MODEL_DEDUP", "")         # 去重，空则 fallback

# ── 采集 ──
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
NVD_RESULTS_PER_PAGE = int(os.getenv("NVD_RESULTS_PER_PAGE", "10"))
RSS_MAX_ITEMS = int(os.getenv("RSS_MAX_ITEMS", "20"))

# ── 邮件 ──
MAIL_HOST = os.getenv("MAIL_HOST", "")
MAIL_PORT = int(os.getenv("MAIL_PORT", "25"))
MAIL_USER = os.getenv("MAIL_USER", "")
MAIL_PASS = os.getenv("MAIL_PASS", "")
MAIL_TO_LIST = os.getenv("MAIL_TO_LIST", "").split(",") if os.getenv("MAIL_TO_LIST") else []
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USER)

# ── 存储 ──
# 本地开发：默认 data/audit.db；FC 生产环境：通过环境变量指向 NAS 路径
AUDIT_DB_PATH = os.getenv("AUDIT_DB_PATH", "data/audit.db")

# ── 路径 ──
SOURCES_PATH = os.path.join(os.path.dirname(__file__), "sources.json")

# ── 调试 ──
DEBUG = _bool_env("DEBUG", False)
DEDUP_USE_AI = _bool_env("DEDUP_USE_AI", False)
