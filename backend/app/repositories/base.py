# -*- coding: utf-8 -*-
"""Repository 抽象基类。

定义数据访问契约。具体实现（文件 / PG）在子类中。

数据返回结构以"原始 JSON 字段"为准（与 ``backend/data/*.json`` 一致），
保证上层 service / API 的输出与重构前**逐字段一致**。
"""
from __future__ import annotations

from abc import ABC
from typing import Any

from app.repositories.file_store import FileStore


class BaseRepo(ABC):
    """所有 repository 的基类。提供共享的文件访问能力。"""

    def __init__(self, store: FileStore | None = None) -> None:
        self.store = store or FileStore()

    # ---- 通用工具 ----
    def _read_json(self, *rel: str) -> Any:
        return self.store.read_json(*rel)
