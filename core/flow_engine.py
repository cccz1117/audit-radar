# -*- coding: utf-8 -*-
"""Flow Engine：声明式工作流引擎。

2025-2026 年 Flow Engineering 范式的轻量实现。
用 YAML 定义 LLM 调用链 + 代码节点的编排，无需 LangGraph。
"""
import importlib
import json
import re
from typing import Any, Dict, List

import yaml

import config


class FlowEngine:
    """轻量级工作流引擎。"""

    def __init__(self, flow_path: str = "flow.yaml"):
        with open(flow_path, "r", encoding="utf-8") as f:
            self.flow = yaml.safe_load(f)
        self.context: Dict[str, Any] = {}

    def run(self, initial_inputs: Dict[str, Any] = None) -> Dict[str, Any]:
        """顺序执行工作流节点。"""
        self.context = initial_inputs or {}
        nodes = self.flow["pipeline"]["nodes"]

        for node in nodes:
            nid = node["id"]
            print(f"\n▶️ [{nid}] 类型:{node['type']}")
            result = self._execute(node)
            self.context[nid] = result
            print(f"   ✅ 完成 → 输出存入 context['{nid}']")

        return self.context

    def _execute(self, node: Dict) -> Any:
        """根据节点类型分发执行。"""
        t = node["type"]
        if t == "code":
            return self._run_code(node)
        if t == "llm":
            return self._run_llm(node)
        if t == "condition":
            return self._run_condition(node)
        raise ValueError(f"未知节点类型: {t}")

    def _resolve_input(self, raw: Any) -> Any:
        """解析输入中的 ${node_id} 占位符。"""
        if isinstance(raw, str):
            pattern = r"\$\{(\w+)(?:\.(\w+))?\}"
            def replacer(m):
                key = m.group(1)
                sub = m.group(2)
                val = self.context.get(key, f"[missing:{key}]")
                if sub and isinstance(val, dict):
                    return str(val.get(sub, val))
                return str(val) if not isinstance(val, (dict, list)) else json.dumps(val, ensure_ascii=False)
            return re.sub(pattern, replacer, raw)
        if isinstance(raw, list):
            return [self._resolve_input(item) for item in raw]
        return raw

    def _run_code(self, node: Dict) -> Any:
        """执行 Python 代码节点。"""
        module_path = node["module"]
        func_name = node["function"]
        raw_input = node.get("input")

        # 动态导入
        mod = importlib.import_module(module_path)
        func = getattr(mod, func_name)

        # 解析输入
        resolved = self._resolve_input(raw_input) if raw_input is not None else None

        # 如果 resolved 是列表且函数需要 *args，展开；否则直接传
        if isinstance(resolved, list) and node.get("spread", False):
            return func(*resolved)
        if resolved is not None:
            return func(resolved)
        return func()

    def _run_llm(self, node: Dict) -> Any:
        """执行 LLM 节点。"""
        import requests

        # 读取 System Prompt
        prompt_path = node["system_prompt"]
        with open(prompt_path, "r", encoding="utf-8") as f:
            system_prompt = f.read()

        # 解析用户输入（包含 ${node_id} 引用）
        user_input = self._resolve_input(node.get("input", ""))

        # 限制长度（防止超过 token 上限）
        if isinstance(user_input, str) and len(user_input) > 12000:
            user_input = user_input[:12000] + "\n...[截断]"

        model = node.get("model", config.MODEL_NAME)
        temperature = node.get("temperature", config.MODEL_TEMPERATURE)
        max_tokens = node.get("max_tokens", config.MODEL_MAX_TOKENS)

        headers = {
            "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_input},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        r = requests.post(
            f"{config.DASHSCOPE_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=180,
        )
        r.raise_for_status()
        content = r.json()["choices"][0]["message"]["content"]

        # 如果配置了 output_parser，尝试解析
        parser = node.get("output_parser")
        if parser == "json":
            return self._safe_json_parse(content)
        return content

    def _run_condition(self, node: Dict) -> Any:
        """执行条件分支节点。"""
        expr = node["if"]
        # 简单表达式求值：如 "len(${screen}) < 10"
        resolved_expr = self._resolve_input(expr)
        try:
            condition = eval(resolved_expr, {"__builtins__": {}}, {})
        except Exception:
            condition = False

        print(f"   条件: {resolved_expr} → {condition}")

        if condition:
            # 执行 then 分支的节点
            return self._execute_branch(node["then"])
        else:
            return self._execute_branch(node.get("else"))

    def _execute_branch(self, branch_nodes: List[Dict]) -> Any:
        """执行分支内的子节点序列。"""
        if not branch_nodes:
            return None
        last_result = None
        for sub in branch_nodes:
            last_result = self._execute(sub)
            self.context[sub["id"]] = last_result
        return last_result

    @staticmethod
    def _safe_json_parse(text: str) -> Any:
        """兼容 markdown 代码块的 JSON 解析。"""
        t = text.strip()
        if t.startswith("```"):
            t = t.strip("`").strip()
            if t.lower().startswith("json"):
                t = t[4:].strip()
        try:
            return json.loads(t)
        except json.JSONDecodeError:
            return text
