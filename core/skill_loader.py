# -*- coding: utf-8 -*-
"""Skill 加载工具。"""
import os
from typing import Dict

import yaml


SKILLS_DIR = os.path.join(os.path.dirname(__file__), "..", "skills")


def load_skill(skill_name: str) -> Dict[str, str]:
    """读取指定 skill 的元数据和 system prompt。

    Args:
        skill_name: skill 目录名，如 "rss-audit-screener"。

    Returns:
        {
            "name": str,
            "description": str,
            "entrypoint": str,
            "system_prompt": str,
        }
    """
    path = os.path.join(SKILLS_DIR, skill_name, "SKILL.md")
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()

    if text.startswith("---"):
        _, front, body = text.split("---", 2)
        meta = yaml.safe_load(front) or {}
    else:
        meta, body = {}, text

    return {
        "name": meta.get("name", skill_name),
        "description": meta.get("description", ""),
        "entrypoint": meta.get("entrypoint", ""),
        "system_prompt": body.strip(),
    }


def load_skill_prompt(skill_name: str) -> str:
    """只读取 skill 的 system prompt 正文。"""
    return load_skill(skill_name)["system_prompt"]
