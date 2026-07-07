# -*- coding: utf-8 -*-
"""计算引擎惰性加载器。

复用仓库内现有的 ``backend/nlu.py`` / ``backend/report_gen.py`` /
``backend/profile.py`` / ``backend/structures3d.py``，**零改动**。
仅在本模块中通过 ``importlib`` 延迟导入并缓存，避免 import 副作用
（旧模块在 import 时即读盘 + 构建 TF-IDF 矩阵）。
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
from types import ModuleType
from typing import Optional

from app.core.config import get_settings
from app.core.logging import get_logger

_log = get_logger(__name__)


def _ensure_backend_on_path() -> None:
    """把 ``backend/`` 目录加入 sys.path，使旧模块（nlu/report_gen/profile/
    structures3d）能以顶层名导入。

    旧 ``app.py`` 在模块顶部执行 ``sys.path.insert(0, HERE)``。此处复刻同样
    行为，保证计算引擎零改动。
    """
    backend_dir = str(get_settings().backend_dir)
    if backend_dir not in sys.path:
        sys.path.insert(0, backend_dir)


_ensure_backend_on_path()

# 各引擎按需加载、单例缓存
_CACHE: dict[str, ModuleType] = {}
_LOCK = threading.Lock()

_ENGINE_MODULES = {
    "nlu": "nlu",
    "report": "report_gen",
    "profile": "profile",
    "structures3d": "structures3d",
    "voxel": "voxel_model",
}


def _load(kind: str) -> ModuleType:
    """加载并缓存指定引擎模块。线程安全。"""
    if kind in _CACHE:
        return _CACHE[kind]
    with _LOCK:
        if kind in _CACHE:
            return _CACHE[kind]
        mod_name = _ENGINE_MODULES.get(kind)
        if mod_name is None:
            raise KeyError(f"未知引擎: {kind}")
        _log.debug("加载计算引擎 {} -> {}", kind, mod_name)
        mod = importlib.import_module(mod_name)
        _CACHE[kind] = mod
        return mod


def get_nlu():
    """NLU / 对话 / RAG 引擎（= backend/nlu.py）。"""
    return _load("nlu")


def get_report():
    """报告生成引擎（= backend/report_gen.py）。"""
    return _load("report")


def get_profile():
    """沿线地质纵剖面引擎（= backend/profile.py）。"""
    return _load("profile")


def get_structures3d():
    """三维地质结构引擎（= backend/structures3d.py）。"""
    return _load("structures3d")


def get_voxel():
    """体素地质模型引擎（= backend/voxel_model.py）。"""
    return _load("voxel")


def preload_engines() -> None:
    """预热全部计算引擎。在 lifespan 启动阶段调用。

    若引擎模块因数据缺失加载失败，仅记录错误、不抛出 —— 允许系统在
    不完整数据下提供 /api/health 等基础能力。
    """
    for kind in _ENGINE_MODULES:
        try:
            _load(kind)
        except Exception as exc:  # noqa: BLE001
            _log.error("预加载引擎 {} 失败：{}", kind, exc)


def release_engines() -> None:
    """释放引擎缓存。在 lifespan 关闭阶段调用。"""
    with _LOCK:
        _CACHE.clear()


def get_engine(kind: str) -> Optional[ModuleType]:
    """通用获取接口（缺失返回 None，便于弱依赖场景）。"""
    try:
        return _load(kind)
    except Exception:  # noqa: BLE001
        return None
