# -*- coding: utf-8 -*-
"""统一 LLM 客户端：支持百炼(DeepSeek)、智谱(GLM)、Moonshot(Kimi)。

用法：
    from core.llm_client import chat_completion
    resp = chat_completion(system="...", user="...", task="screen")

环境变量控制供应商：
    LLM_PROVIDER=dashscope|zhipu|moonshot
    或任务级覆盖：MODEL_SCREEN=dashscope:deepseek-r1
"""
import json
import os
from typing import Optional

import requests

import config


# ── 供应商配置表 ──
PROVIDERS = {
    "dashscope": {
        "base_url": config.DASHSCOPE_BASE_URL,
        "api_key": config.DASHSCOPE_API_KEY,
    },
    "zhipu": {
        "base_url": config.ZHIPU_BASE_URL,
        "api_key": config.ZHIPU_API_KEY,
    },
    "moonshot": {
        "base_url": config.MOONSHOT_BASE_URL,
        "api_key": config.MOONSHOT_API_KEY,
    },
}


def _resolve_model(task: str = "") -> tuple[str, str]:
    """解析当前任务该用哪个供应商和模型。

    优先级：
      1. 任务级环境变量（如 MODEL_SCREEN=zhipu:glm-4-flash）
      2. 全局 LLM_PROVIDER + MODEL_NAME
      3. 默认值 dashscope + deepseek-v4-flash

    返回：(provider, model_name)
    """
    task_env = {
        "screen": config.MODEL_SCREEN,
        "rank": config.MODEL_RANK,
        "generate": config.MODEL_GENERATE,
        "dedup": config.MODEL_DEDUP,
    }.get(task, "")

    if task_env and ":" in task_env:
        provider, model = task_env.split(":", 1)
        return provider.strip(), model.strip()

    if task_env:
        # 只写了模型名，供应商走全局
        return config.LLM_PROVIDER, task_env

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
        raise ValueError(f"未知供应商: {provider}，请检查 LLM_PROVIDER 或 MODEL_* 环境变量")

    api_key = cfg["api_key"]
    if not api_key:
        raise ValueError(f"供应商 {provider} 的 API Key 未配置（{provider.upper()}_API_KEY）")

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

    if config.DEBUG:
        print(f"  [DEBUG] LLM call: provider={provider}, model={model_name}, task={task}, input_chars={len(user)}")

    resp = requests.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json=payload,
        timeout=timeout,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"]

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
