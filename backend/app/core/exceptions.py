# -*- coding: utf-8 -*-
"""统一异常体系。

设计目标
--------
- ``services`` 层抛出领域异常，**不 import fastapi**，便于单测。
- 全局 exception handler 在表现层把领域异常映射为 HTTP 响应。
- 兼容现有 API：``NotFoundError`` -> 404、``ValidationError`` -> 400，
  与原 ``raise HTTPException(404, ...)`` 行为一致。
"""
from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """所有业务异常的基类。"""

    status_code: int = 500
    detail: str = "内部错误"

    def __init__(self, detail: str | None = None, *, status_code: int | None = None):
        self.detail = detail if detail is not None else self.detail
        if status_code is not None:
            self.status_code = status_code
        super().__init__(self.detail)


class NotFoundError(AppError):
    status_code = 404
    detail = "资源不存在"


class ValidationError(AppError):
    status_code = 400
    detail = "请求参数无效"


class EngineError(AppError):
    """计算引擎（NLU / 报告 / 剖面 / 3D）内部错误。"""

    status_code = 500
    detail = "计算引擎处理失败"


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器。在应用工厂中调用。"""

    @app.exception_handler(NotFoundError)
    async def _handle_not_found(_: Request, exc: NotFoundError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(ValidationError)
    async def _handle_validation(_: Request, exc: ValidationError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )

    @app.exception_handler(EngineError)
    async def _handle_engine(_: Request, exc: EngineError):
        # 不向客户端泄漏内部堆栈
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail or "计算引擎处理失败"},
        )

    @app.exception_handler(AppError)
    async def _handle_app(_: Request, exc: AppError):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
