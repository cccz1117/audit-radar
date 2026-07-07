# -*- coding: utf-8 -*-
"""周报生成器：从 deep_dive_queue 挑选主题并生成 HTML 周报。"""
import json
from typing import List, Dict

import requests

import config
from core.skill_loader import load_skill_prompt


class WeeklyGenerator:
    """基于深度挖掘队列生成周报。"""

    def __init__(self):
        self.system_prompt = load_skill_prompt("weekly-report-generator")

    def generate(self, candidates: List[Dict], week_id: str) -> Dict:
        """输入候选池，返回 {"topics": [...], "html": "..."}。"""
        if not candidates:
            return {"topics": [], "html": self._empty_html(week_id)}

        selected = self._select_candidates(candidates)
        user_prompt = self._format_prompt(selected, week_id)
        raw = self._call_llm(user_prompt)
        return self._parse_output(raw, selected, week_id)

    def _select_candidates(self, candidates: List[Dict]) -> List[Dict]:
        """简单策略：最多选 3 个。未来可替换为 LLM 排序。"""
        # 按来源去重 + 按审计相关度猜测排序
        seen_sources = set()
        diversified = []
        for c in sorted(
            candidates,
            key=lambda x: (
                x.get("deep_dive_reason", "").count("AI"),
                x.get("deep_dive_reason", "").count("银行"),
                x.get("date", ""),
            ),
            reverse=True,
        ):
            source = c.get("source", "")
            if source not in seen_sources:
                diversified.append(c)
                seen_sources.add(source)
            elif len(seen_sources) >= 2:
                # 已有至少两个不同来源后，允许同来源的优质候选填补剩余位置
                diversified.append(c)
            if len(diversified) >= 3:
                break
        return diversified

    def _format_prompt(self, selected: List[Dict], week_id: str) -> str:
        lines = [f"周次：{week_id}", f"候选数量：{len(selected)}", ""]
        for i, c in enumerate(selected, 1):
            lines.append(f"[{i}] {c.get('title', '')}")
            lines.append(f"    来源：{c.get('source', '')}")
            lines.append(f"    链接：{c.get('link', '')}")
            lines.append(f"    音频：{c.get('audio_url', '')}")
            lines.append(f"    摘要：{c.get('summary', '')[:400]}")
            lines.append(f"    入选理由：{c.get('deep_dive_reason', '')}")
            lines.append(f"    初步审计方向：{c.get('audit_mapping_guess', '')}")
            lines.append("")
        return "\n".join(lines)

    def _call_llm(self, user_prompt: str) -> str:
        """调用百炼 API。"""
        headers = {
            "Authorization": f"Bearer {config.DASHSCOPE_API_KEY}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": config.MODEL_NAME,
            "messages": [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": config.MODEL_TEMPERATURE,
            "max_tokens": config.MODEL_MAX_TOKENS,
        }
        r = requests.post(
            f"{config.DASHSCOPE_BASE_URL}/chat/completions",
            headers=headers,
            json=payload,
            timeout=180,
        )
        r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"]

    def _parse_output(self, raw: str, selected: List[Dict], week_id: str) -> Dict:
        """解析 LLM 输出。失败时回退到简单模板。"""
        text = raw.strip()
        if text.startswith("```"):
            text = text.strip("`").strip()
            if text.lower().startswith("json"):
                text = text[4:].strip()
        try:
            data = json.loads(text)
            return {
                "topics": data.get("topics", []),
                "html": data.get("html", self._fallback_html(selected, week_id)),
            }
        except json.JSONDecodeError:
            # LLM 直接返回 HTML
            if "<html" in text or "<!DOCTYPE" in text:
                return {"topics": [], "html": text}
            return {"topics": [], "html": self._fallback_html(selected, week_id)}

    def _empty_html(self, week_id: str) -> str:
        return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"></head>
<body style="font-family:sans-serif;max-width:680px;margin:0 auto;padding:24px;">
<h1>AI审计情报周报 · {week_id}</h1>
<p>本周暂无深度挖掘候选。</p>
<div style="margin-top:32px;color:#999;font-size:12px;">
本报告基于公开播客/文章摘要整理，仅供内部学习，不构成投资建议。
</div>
</body></html>"""

    def _fallback_html(self, selected: List[Dict], week_id: str) -> str:
        """LLM 失败时的兜底 HTML。"""
        parts = [
            "<!DOCTYPE html><html><head><meta charset=\"utf-8\"></head>",
            '<body style="font-family:sans-serif;max-width:680px;margin:0 auto;padding:24px;line-height:1.7;">',
            f"<h1>AI审计情报周报 · {week_id}</h1>",
            f"<p>本周共入选 {len(selected)} 个深度主题。</p>",
        ]
        for i, c in enumerate(selected, 1):
            parts.append(f"<h2>{i}. {c.get('title', '')}</h2>")
            parts.append(f"<p style=\"color:#888;font-size:13px;\">来源：{c.get('source', '')} · <a href=\"{c.get('link', '')}\">原文链接</a></p>")
            parts.append(f"<p><b>入选理由：</b>{c.get('deep_dive_reason', '')}</p>")
            parts.append(f"<p><b>审计方向：</b>{c.get('audit_mapping_guess', '')}</p>")
        parts.append('<div style="margin-top:32px;color:#999;font-size:12px;">本报告基于公开播客/文章摘要整理，仅供内部学习，不构成投资建议。</div>')
        parts.append("</body></html>")
        return "\n".join(parts)
