# -*- coding: utf-8 -*-
"""集中配置管理。所有密钥从环境变量读取，适配阿里云 FC 与本地测试。"""
import os

# -- 大模型 --
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
MODEL_NAME = os.getenv("MODEL_NAME", "deepseek-v4-flash")
MODEL_TEMPERATURE = float(os.getenv("MODEL_TEMPERATURE", "0.3"))
MODEL_MAX_TOKENS = int(os.getenv("MODEL_MAX_TOKENS", "8192"))

# -- 采集 --
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
NVD_RESULTS_PER_PAGE = int(os.getenv("NVD_RESULTS_PER_PAGE", "10"))
RSS_MAX_ITEMS = int(os.getenv("RSS_MAX_ITEMS", "20"))

# -- 邮件 --
MAIL_HOST = os.getenv("MAIL_HOST", "")
MAIL_PORT = int(os.getenv("MAIL_PORT", "587"))
MAIL_USER = os.getenv("MAIL_USER", "")
MAIL_PASS = os.getenv("MAIL_PASS", "")
MAIL_TO_LIST = os.getenv("MAIL_TO_LIST", "").split(",")  # 逗号分隔
MAIL_FROM = os.getenv("MAIL_FROM", MAIL_USER)

# -- 路径 --
PROMPTS_DIR = os.path.join(os.path.dirname(__file__), "prompts")
SOURCES_PATH = os.path.join(os.path.dirname(__file__), "sources.json")

# -- 调试 --
DEBUG = os.getenv("DEBUG", "false").lower() in ("1", "true", "yes")
