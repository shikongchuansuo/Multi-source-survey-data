# -*- coding: utf-8 -*-
"""SQLAlchemy 引擎与会话工厂。

仅 ``use_db=True`` 时由 ``core/lifespan`` 调用 ``init_db_engine()``。

设计要点
--------
- 同步引擎（业务为计算密集型，无并发压力，避免 async DB 驱动复杂度）。
- ``check_connection`` 在启动时验证连通性，失败则回退文件模式。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings
from app.core.logging import get_logger

_log = get_logger(__name__)

_engine: Optional[Engine] = None
_SessionLocal: Optional[sessionmaker] = None


def init_db_engine() -> None:
    """创建数据库引擎与会话工厂。"""
    global _engine, _SessionLocal
    settings = get_settings()
    _engine = create_engine(
        settings.database_url,
        echo=settings.pg_echo,
        pool_pre_ping=True,
        future=True,
    )
    _SessionLocal = sessionmaker(
        bind=_engine, autoflush=False, autocommit=False, future=True,
    )


def get_engine() -> Engine:
    if _engine is None:
        init_db_engine()
    assert _engine is not None
    return _engine


def get_session() -> Session:
    """返回一个 DB Session（router 依赖注入用）。"""
    if _SessionLocal is None:
        init_db_engine()
    assert _SessionLocal is not None
    return _SessionLocal()


def check_connection() -> None:
    """执行 ``SELECT 1`` 验证连通性 + PostGIS 扩展可用性。"""
    assert _engine is not None
    with _engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        # 验证 PostGIS 扩展（若未安装则警告）
        try:
            conn.execute(text("SELECT PostGIS_Version()"))
        except Exception as exc:  # noqa: BLE001
            _log.warning("PostGIS 扩展未安装或不可用：{}", exc)


def dispose_db_engine() -> None:
    """关闭连接池。"""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
