# -*- coding: utf-8 -*-
"""统一 LLM 客户端：支持多供应商官方 API + 百炼代理。

用法：
    from core.llm_client import chat_completion
    resp = chat_completion(system="...", user="...", task="screen")

配置方式：
  1. 全局默认：LLM_PROVIDER + MODEL_NAME
  2. 任务级覆盖：MODEL_SCREEN=deepseek:deepseek-v4-pro
  3. 模型名简写（自动推断供应商）：MODEL_RANK=deepseek-v4-pro

供应商说明：
  - deepseek:  DeepSeek 官方 API（文档解析/筛选/生成任务用）
  - moonshot:  Moonshot 官方 API
  - dashscope: 阿里云百炼（预留用于 STT 等非 chat 任务）
  - zhipu:     智谱 GLM（保留代码，暂不启用）
"""
import json
import time
from typing import Optional

import requests

import config


# 瞬时故障重试策略：429/5xx/超时/连接失败可恢复，指数退避后重试
MAX_RETRIES = 2               # 重试次数（共尝试 1+2=3 次）
RETRY_BACKOFF = (5, 15)       # 各次重试前等待秒数
RETRYABLE_STATUS = {429, 500, 502, 503, 504}


# ── 供应商配置表 ──
# 新增供应商只需在这里加一行，上层零感知
PROVIDERS = {
    "deepseek": {
        "base_url": config.DEEPSEEK_BASE_URL,
        "api_key": config.DEEPSEEK_API_KEY,
    },
    "moonshot": {
        "base_url": config.MOONSHOT_BASE_URL,
        "api_key": config.MOONSHOT_API_KEY,
    },
    "dashscope": {
        "base_url": config.DASHSCOPE_BASE_URL,
        "api_key": config.DASHSCOPE_API_KEY,
    },
    "zhipu": {
        "base_url": config.ZHIPU_BASE_URL,
        "api_key": config.ZHIPU_API_KEY,
    },
}


# ── 模型名前缀 → 供应商自动推断表 ──
# 写模型名就能自动路由，不需要指定 provider
MODEL_PREFIX_MAP = {
    "deepseek-": "deepseek",    # deepseek-v4-flash / deepseek-v4-pro（官方模型 ID）
    "ds-": "deepseek",          # 兼容旧缩写（注意：官方 API 不接受 ds- 开头的模型名）
    "kimi-": "moonshot",        # kimi-k2-6
    "glm-": "zhipu",            # glm-4-flash
}


def _infer_provider(model_name: str) -> str:
    """根据模型名前缀推断供应商。"""
    for prefix, provider in MODEL_PREFIX_MAP.items():
        if model_name.lower().startswith(prefix):
            return provider
    return config.LLM_PROVIDER


def _resolve_model(task: str = "") -> tuple[str, str]:
    """解析当前任务该用哪个供应商和模型。

    优先级：
      1. 任务级环境变量（如 MODEL_SCREEN=deepseek:deepseek-v4-pro 或 MODEL_SCREEN=deepseek-v4-pro）
      2. 根据模型名前缀自动推断供应商
      3. 全局 LLM_PROVIDER + MODEL_NAME
      4. 默认值 deepseek + deepseek-v4-flash

    返回：(provider, model_name)
    """
    task_env = {
        "screen": config.MODEL_SCREEN,
        "rank": config.MODEL_RANK,
        "generate": config.MODEL_GENERATE,
        "dedup": config.MODEL_DEDUP,
        "resonance": config.MODEL_RESONANCE,
    }.get(task, "")

    if task_env:
        if ":" in task_env:
            # 显式指定供应商：deepseek:deepseek-v4-pro
            provider, model = task_env.split(":", 1)
            return provider.strip(), model.strip()
        else:
            # 只写模型名：deepseek-v4-pro → 自动推断供应商
            return _infer_provider(task_env), task_env.strip()

    # 走全局默认
    return config.LLM_PROVIDER, config.MODEL_NAME


def chat_completion(
    system: str,
    user: str,
    task: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: int = 120,
) -> str:
    """调用大模型，返回文本内容。

    Args:
        system: System Prompt
        user: User Prompt
        task: 任务标识（screen/rank/generate/dedup），用于路由到不同模型
        temperature: 温度，默认从 config 读取
        max_tokens: 最大 token，默认从 config 读取
        timeout: 请求超时（秒）

    Returns:
        模型返回的文本内容
    """
    provider, model_name = _resolve_model(task)
    cfg = PROVIDERS.get(provider)

    if not cfg:
        raise ValueError(
            f"未知供应商: {provider}，请检查 LLM_PROVIDER / MODEL_* 环境变量。"
            f"可用供应商: {list(PROVIDERS.keys())}"
        )

    api_key = cfg["api_key"]
    if not api_key:
        raise ValueError(
            f"供应商 {provider} 的 API Key 未配置。"
            f"请设置 {provider.upper()}_API_KEY 环境变量。"
        )

    base_url = cfg["base_url"].rstrip("/")
    temp = temperature if temperature is not None else config.MODEL_TEMPERATURE
    max_tok = max_tokens if max_tokens is not None else config.MODEL_MAX_TOKENS

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model_name,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temp,
        "max_tokens": max_tok,
    }

    # DeepSeek V4 思考模式控制：默认不干预（让模型用官方默认），
    # 可配环境变量显式开启 high/max 或关闭 none
    if provider == "deepseek":
        effort = config.DEEPSEEK_REASONING_EFFORT
        if effort in ("high", "max"):
            payload["reasoning_effort"] = effort
        elif effort == "none":
            payload["thinking"] = {"type": "disabled"}

    if config.DEBUG:
        print(f"  [DEBUG] LLM call: provider={provider}, model={model_name}, task={task}, input_chars={len(user)}")

    last_err: Optional[Exception] = None
    for attempt in range(MAX_RETRIES + 1):
        if attempt > 0:
            wait = RETRY_BACKOFF[min(attempt - 1, len(RETRY_BACKOFF) - 1)]
            print(f"  ↻ LLM 第 {attempt} 次重试（等待 {wait}s）...")
            time.sleep(wait)
        try:
            resp = requests.post(
                f"{base_url}/chat/completions",
                headers=headers,
                json=payload,
                timeout=timeout,
            )
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            # 瞬时网络故障：可重试
            last_err = RuntimeError(f"LLM 请求超时/连接失败（{timeout}s）: {e}")
            continue

        # 不可恢复错误：立即失败，不重试
        if resp.status_code == 401:
            raise RuntimeError(f"LLM API 认证失败（401）: 请检查 {provider.upper()}_API_KEY 是否正确")
        if resp.status_code in RETRYABLE_STATUS:
            last_err = RuntimeError(f"LLM API 瞬时错误（{resp.status_code}）: {resp.text[:200]}")
            continue
        if resp.status_code >= 400:
            raise RuntimeError(f"LLM API 错误（{resp.status_code}）: {resp.text[:500]}")
        break  # 成功
    else:
        raise RuntimeError(f"LLM 请求失败，已重试 {MAX_RETRIES} 次: {last_err}")

    # 解析响应 JSON
    try:
        data = resp.json()
    except json.JSONDecodeError as e:
        raise RuntimeError(f"LLM 返回非 JSON 响应: {resp.text[:500]}")

    # 防御性检查 choices
    choices = data.get("choices")
    if not choices or not isinstance(choices, list):
        raise RuntimeError(f"LLM 响应缺少 choices 字段: {data}")

    try:
        content = choices[0]["message"]["content"]
    except (KeyError, IndexError) as e:
        raise RuntimeError(f"LLM 响应格式异常: {data}")

    if config.DEBUG:
        print(f"  [DEBUG] LLM output: {content[:500]}")

    return content


def safe_json_parse(text: str) -> Optional[dict]:
    """兼容 markdown 代码块的 JSON 解析。"""
    t = text.strip()
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t.lower().startswith("json"):
            t = t[4:].strip()
    try:
        return json.loads(t)
    except json.JSONDecodeError:
        return None


def strip_code_fence(text: str) -> str:
    """剥离 LLM 输出首尾的 markdown 代码围栏（```html ... ```）。

    用于 HTML 等纯文本产物：邮件正文中残留 ``` 会导致部分邮箱网关
    解析异常（拒收或消息头丢失），必须在生成层剥掉。
    仅处理整体包裹的情况；正文中不含代码围栏时原样返回。
    """
    t = text.strip()
    if not t.startswith("```"):
        return t
    # 去掉首行围栏（```html / ```HTML / ```）
    nl = t.find("\n")
    if nl == -1:
        return t.strip("`").strip()
    t = t[nl + 1:]
    # 去掉结尾围栏
    end = t.rstrip()
    if end.endswith("```"):
        t = end[:-3]
    return t.strip()
