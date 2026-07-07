# -*- coding: utf-8 -*-
"""结构化日志。

基于 ``loguru``，提供统一格式与请求 ID 注入。所有业务代码应通过
``get_logger(__name__)`` 获取 logger，避免直接 ``import logging``。
"""
from __future__ import annotations

import sys
import uuid
from contextvars import ContextVar

from loguru import logger

from app.core.config import get_settings

# 请求级别的 trace id（中间件注入）
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")


def _patcher(record):
    """把 request_id 注入到每条日志的 extra 字段。"""
    record["extra"]["request_id"] = request_id_var.get()


def setup_logging() -> None:
    """初始化日志格式。在 lifespan 启动时调用一次。"""
    settings = get_settings()
    logger.remove()
    logger.configure(patcher=_patcher)

    level = "DEBUG" if settings.env == "dev" else "INFO"
    fmt = (
        "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{extra[request_id]}</cyan> | "
        "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
        "<level>{message}</level>"
    )
    logger.add(
        sys.stderr,
        level=level,
        format=fmt,
        colorize=True,
        backtrace=True,
        diagnose=settings.env == "dev",
    )


def get_logger(name: str = __name__):
    """获取一个带模块名的 logger。"""
    return logger.bind(name=name)


def new_request_id() -> str:
    """生成一个新的请求 ID（短形式，便于日志阅读）。"""
    return uuid.uuid4().hex[:12]
