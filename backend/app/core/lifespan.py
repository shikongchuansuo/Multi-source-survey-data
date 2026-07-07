# -*- coding: utf-8 -*-
"""应用生命周期管理。

启动顺序
--------
1. 加载 Settings（已在 import 时完成）
2. 初始化日志
3. 连接 PG（``use_db=True`` 时）
4. 校验 ``data_dir`` 完整性
5. 预热计算引擎（NLU TF-IDF、DEM 网格缓存）

关闭顺序（反向）
----------------
1. 释放引擎缓存
2. 关闭 DB 连接池
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from app.core.config import get_settings
from app.core.logging import get_logger, setup_logging
from app.engines.loader import get_engine, preload_engines


def _check_data_dir() -> None:
    """校验数据目录完整性（manifest 是一切的基础）。"""
    settings = get_settings()
    manifest = settings.data_dir / "manifest.json"
    if not manifest.exists():
        # 仅警告，不阻断启动 —— 允许在无数据状态下提供 /api/health
        get_logger(__name__).warning(
            "数据目录不完整：缺少 {}。请先运行 python backend/generate_data.py",
            manifest,
        )


def _setup_db() -> None:
    """初始化数据库连接（仅 ``use_db=True`` 时）。"""
    settings = get_settings()
    if not settings.use_db:
        get_logger(__name__).info("use_db=False，采用纯文件模式（离线兜底）。")
        return
    # 延迟导入，避免无 PG 环境下 import 失败
    try:
        from app.db.session import init_db_engine, check_connection

        init_db_engine()
        check_connection()
        get_logger(__name__).info("PostgreSQL 连接就绪。")
    except Exception as exc:  # noqa: BLE001
        get_logger(__name__).error(
            "数据库初始化失败，回退到文件模式：{}", exc
        )
        # 不抛出 —— 允许以文件模式继续运行（兼容红线）
        settings.use_db = False


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """FastAPI lifespan 上下文。"""
    log = get_logger(__name__)
    settings = get_settings()

    setup_logging()
    log.info("启动 {} (env={}, use_db={})",
             settings.app_name, settings.env, settings.use_db)

    _check_data_dir()
    _setup_db()

    # 预热计算引擎（惰性加载 + 缓存）
    try:
        preload_engines()
        log.info("计算引擎预热完成（NLU/报告/剖面/3D）。")
    except Exception as exc:  # noqa: BLE001
        log.error("计算引擎预热失败：{}", exc)

    log.info("系统就绪 ✓")

    yield

    # ---- 关闭 ----
    log.info("正在关闭服务...")
    try:
        from app.engines.loader import release_engines
        release_engines()
    except Exception:  # noqa: BLE001
        pass
    if settings.use_db:
        try:
            from app.db.session import dispose_db_engine
            dispose_db_engine()
        except Exception:  # noqa: BLE001
            pass
    log.info("已关闭。")


# 提前实例化，便于单元测试引用
__all__ = ["lifespan", "get_engine"]
