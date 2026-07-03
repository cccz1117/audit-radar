# -*- coding: utf-8 -*-
"""Flow Engine 辅助工具函数。"""


def merge_candidates(*args):
    """合并多个候选列表（用于补充采集后合并）。"""
    merged = []
    for arg in args:
        if isinstance(arg, list):
            merged.extend(arg)
    return merged


def identity(x):
    """恒等函数（条件分支的 else 路径直接透传）。"""
    return x
