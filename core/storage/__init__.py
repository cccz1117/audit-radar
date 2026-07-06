# -*- coding: utf-8 -*-
"""存储后端抽象与实现。"""
from .base import StorageBackend
from .sqlite_backend import SQLiteBackend

__all__ = ["StorageBackend", "SQLiteBackend"]
