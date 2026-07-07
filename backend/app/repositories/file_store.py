# -*- coding: utf-8 -*-
"""文件存储抽象。

统一封装栅格(PNG) / 点云(PLY) / CSV / world 文件等**文件型数据**的路径
解析与读流，替代散落在旧代码中的 ``os.path.join(DATA, ...)``。

注意：栅格 / 点云 / CSV **始终走文件**（不入数据库），这是设计文档 §六
的明确决策。
"""
from __future__ import annotations

import csv as _csv
import json
from pathlib import Path
from typing import Any, Iterable

from app.core.config import get_settings


class FileStore:
    """文件型数据访问器。所有相对路径以 ``data_dir`` 为根。"""

    def __init__(self, data_dir: Path | None = None) -> None:
        s = get_settings()
        self.root = Path(data_dir if data_dir is not None else s.data_dir)

    # ---- 路径解析 ----
    def resolve(self, *rel_parts: str) -> Path:
        """把相对路径解析为绝对路径。兼容 ``/`` 与 ``\\``。"""
        if not rel_parts:
            return self.root
        joined = "/".join(rel_parts).replace("\\", "/")
        return (self.root / joined).resolve()

    # ---- JSON ----
    def read_json(self, *rel_parts: str) -> Any:
        path = self.resolve(*rel_parts)
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def exists(self, *rel_parts: str) -> bool:
        return self.resolve(*rel_parts).exists()

    # ---- CSV（物探电阻率网格）----
    def read_csv_rows(self, *rel_parts: str, encoding: str = "utf-8-sig") -> Iterable[dict]:
        """以 DictReader 形式逐行读取 CSV。"""
        path = self.resolve(*rel_parts)
        with open(path, "r", encoding=encoding, newline="") as f:
            reader = _csv.DictReader(f)
            for row in reader:
                yield row

    # ---- 文本 ----
    def read_text(self, *rel_parts: str, encoding: str = "utf-8") -> str:
        return self.resolve(*rel_parts).read_text(encoding=encoding)


# 单例
_store: FileStore | None = None


def get_file_store() -> FileStore:
    global _store
    if _store is None:
        _store = FileStore()
    return _store
