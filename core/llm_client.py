# -*- coding: utf-8 -*-
"""统一 LLM 客户端：支持多供应商官方 API + 百炼代理。

用法：
    from core.llm_client import chat_completion
    resp = chat_completion(system="...", user="...", task="screen")

配置方式：
  1. 全局默认：LLM_PROVIDER + MODEL_NAME
  2. 任务级覆盖：MODEL_SCREEN=deepseek:deepseek-v4-pro
  3. 模型名简写（自动推断供应商）：MODEL_RANK=deepseek-v4-pro
  4. 模型别名（聚合平台专用）：MODEL_GENERATE=bl-glm-5.2 → 百炼 glm-5.2
  5. 降级链（逗号串候选，403 配额用尽自动切换）：
     MODEL_GENERATE=bl-glm-5.2,deepseek-v4-flash

供应商说明：
  - deepseek:  DeepSeek 官方 API（文档解析/筛选/生成任务用）
  - moonshot:  Moonshot 官方 API
  - dashscope: 阿里云百炼（聚合平台，经 MODEL_ALIASES 别名调用其托管模型）
  - zhipu:     智谱 GLM（保留代码，暂不启用）
"""
import json
import os
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


# ── 模型别名表：别名 → (provider, 平台真实模型 ID) ──
# 解决聚合平台前缀撞车：百炼上的 GLM 不能按前缀路由到智谱官方。
# 任务级配置直接写别名即可，如 MODEL_GENERATE=bl-glm-5.2；
# 解析优先级：别名 > 显式 provider:model > 前缀推断 > 全局默认。
# 真实模型 ID 以百炼控制台为准，新增模型在此加一行。
MODEL_ALIASES = {
    "bl-glm-5.2": ("dashscope", "glm-5.2"),    # 百炼 GLM-5.2（免费额度 100 万 token，用完即停）

    # ── 百炼 Qwen3.7 系列（免费额度，用于粗筛等批量环节）──
    "bl-qwen3.7-flash":           ("dashscope", "qwen3.7-flash"),
    "bl-qwen3.7-flash-2026-07-15": ("dashscope", "qwen3.7-flash-2026-07-15"),
    "bl-qwen3.7-plus":            ("dashscope", "qwen3.7-plus"),
    "bl-qwen3.7-plus-2026-05-26": ("dashscope", "qwen3.7-plus-2026-05-26"),
    "bl-qwen3.7-max":             ("dashscope", "qwen3.7-max"),
    "bl-qwen3.7-max-preview":     ("dashscope", "qwen3.7-max-preview"),
    "bl-qwen3.7-max-2026-05-17":  ("dashscope", "qwen3.7-max-2026-05-17"),
    "bl-qwen3.7-max-2026-05-20":  ("dashscope", "qwen3.7-max-2026-05-20"),
    "bl-qwen3.7-max-2026-06-08":  ("dashscope", "qwen3.7-max-2026-06-08"),
}


class QuotaExhaustedError(RuntimeError):
    """免费额度用尽（百炼 403 AllocationQuota.FreeTierOnly），触发降级链切换。"""


# 判定 403 是"配额用尽"而非"权限不足"：只看响应体里的错误码
QUOTA_EXHAUSTED_MARKERS = ("AllocationQuota.FreeTierOnly", "AllocationQuota")


def _infer_provider(model_name: str) -> str:
    """根据模型名前缀推断供应商。"""
    for prefix, provider in MODEL_PREFIX_MAP.items():
        if model_name.lower().startswith(prefix):
            return provider
    return config.LLM_PROVIDER


def _resolve_one(spec: str) -> tuple[str, str]:
    """解析单条模型规格：别名 / 显式 provider:model / 前缀推断。"""
    spec = spec.strip()
    if spec in MODEL_ALIASES:
        # 别名：bl-glm-5.2 → (dashscope, glm-5.2)
        return MODEL_ALIASES[spec]
    if ":" in spec:
        # 显式指定供应商：deepseek:deepseek-v4-pro
        provider, model = spec.split(":", 1)
        return provider.strip(), model.strip()
    # 只写模型名：deepseek-v4-pro → 自动推断供应商
    return _infer_provider(spec), spec


def _resolve_candidates(task: str = "") -> list[tuple[str, str]]:
    """解析任务的候选模型链（降级链）。

    任务级环境变量支持逗号串链，按序降级：
      MODEL_GENERATE=bl-glm-5.2,deepseek-v4-flash
      → 先试百炼 GLM-5.2，免费额度耗尽（403 AllocationQuota）自动落回 DeepSeek

    每条规格的解析优先级：别名 > 显式 provider:model > 前缀推断。
    空则走全局 LLM_PROVIDER + MODEL_NAME 单候选。

    返回：[(provider, model_name), ...] 按尝试顺序排列
    """
    task_env = {
        "screen": config.MODEL_SCREEN,
        "rank": config.MODEL_RANK,
        "generate": config.MODEL_GENERATE,
        "dedup": config.MODEL_DEDUP,
        "resonance": config.MODEL_RESONANCE,
        "cluster": config.MODEL_CLUSTER,
    }.get(task, "")

    specs = [s for s in task_env.split(",") if s.strip()]
    if not specs:
        return [(config.LLM_PROVIDER, config.MODEL_NAME)]
    return [_resolve_one(s) for s in specs]


def chat_completion(
    system: str,
    user: str,
    task: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: int = 150,
) -> str:
    """调用大模型，返回文本内容。

    支持候选链降级：任务级配置可逗号串多个候选（如
    MODEL_GENERATE=bl-glm-5.2,deepseek-v4-flash），免费额度用尽
    （百炼 403 AllocationQuota）时自动切换下一候选；链耗尽则报错。

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
    candidates = _resolve_candidates(task)

    for idx, (provider, model_name) in enumerate(candidates):
        try:
            return _chat_once(provider, model_name, system, user,
                              task, temperature, max_tokens, timeout)
        except QuotaExhaustedError:
            if idx < len(candidates) - 1:
                nxt_p, nxt_m = candidates[idx + 1]
                print(f"  ⚠️ {provider}/{model_name} 免费额度用尽（403），降级到 {nxt_p}/{nxt_m}")
                continue
            raise RuntimeError(
                f"候选链已全部耗尽（{[f'{p}/{m}' for p, m in candidates]}），最后一环同样配额不足"
            )
    raise RuntimeError("候选链为空")  # 不可达：_resolve_candidates 至少返回 1 个候选


def _chat_once(
    provider: str,
    model_name: str,
    system: str,
    user: str,
    task: str = "",
    temperature: Optional[float] = None,
    max_tokens: Optional[int] = None,
    timeout: int = 150,
) -> str:
    """对单一 (provider, model) 发起调用，含瞬时故障重试。

    配额用尽（403 AllocationQuota）抛 QuotaExhaustedError，交给外层候选链降级；
    其他错误语义与原 chat_completion 一致。
    """
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

    # Kimi K3 官方限制 temperature 只能为 1，其他值直接报错；强制覆盖
    if provider == "moonshot" and "k3" in model_name.lower():
        temp = 1.0

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

    # DeepSeek V4 思考模式控制：思考 token 与正文共享 max_tokens，
    # 批量粗活（screen/dedup/resonance）开思考会挤占正文预算导致输出截断甚至空响应，
    # 因此这些任务默认关闭思考；可用 DEEPSEEK_REASONING_EFFORT_<TASK> 按任务覆盖，
    # 全局 DEEPSEEK_REASONING_EFFORT 作为兜底（high/max 开启、none 关闭）。
    if provider == "deepseek":
        task_effort = os.getenv(f"DEEPSEEK_REASONING_EFFORT_{task.upper()}", "") if task else ""
        effort = (task_effort or config.DEEPSEEK_REASONING_EFFORT
                  or ("none" if task in ("screen", "dedup", "resonance", "cluster") else "")).lower()
        if effort in ("high", "max"):
            payload["reasoning_effort"] = effort
        elif effort == "none":
            payload["thinking"] = {"type": "disabled"}

    # 百炼（dashscope）思考模式控制：GLM-5.2 / Qwen3.7 等混合思考模型平台默认开思考
    # （思维链按输出 token 计费且挤占 max_tokens 预算），与 DeepSeek 同哲学——
    # 批量粗活（screen/dedup/resonance/cluster）默认关闭，质量任务（rank/generate）留平台默认；
    # 可用 DASHSCOPE_ENABLE_THINKING_<TASK> 按任务覆盖，全局 DASHSCOPE_ENABLE_THINKING 兜底。
    # enable_thinking 非 OpenAI 标准参数，但裸 HTTP POST 直接放 payload 顶层即可（同 curl 示例）。
    if provider == "dashscope":
        task_flag = os.getenv(f"DASHSCOPE_ENABLE_THINKING_{task.upper()}", "") if task else ""
        flag = (task_flag or config.DASHSCOPE_ENABLE_THINKING
                or ("false" if task in ("screen", "dedup", "resonance", "cluster") else "")).lower()
        if flag == "false":
            payload["enable_thinking"] = False
        elif flag == "true":
            payload["enable_thinking"] = True

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
        # 免费额度用尽：抛出降级信号，交给外层候选链（原地重试无意义）。
        # 只对响应体含 AllocationQuota 的 403 降级，其他 403（权限问题）照常报错
        if resp.status_code == 403 and any(m in resp.text for m in QUOTA_EXHAUSTED_MARKERS):
            raise QuotaExhaustedError(f"{provider}/{model_name}: {resp.text[:200]}")
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

    # finish_reason=length 即输出被 max_tokens 截断（思考 token 也会计入），
    # 是排查空响应/半截 JSON 的关键信号；异常情况无论 DEBUG 都告警
    finish = choices[0].get("finish_reason", "")
    if not content:
        print(f"  ⚠️ LLM 返回空内容（finish_reason={finish}，疑似思考 token 占满输出预算）")
    elif finish and finish != "stop":
        print(f"  ⚠️ LLM finish_reason 异常: {finish}（输出可能被截断）")
    if config.DEBUG:
        usage = data.get("usage", {})
        print(f"  [DEBUG] finish_reason={finish} usage={usage}")
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
