# -*- coding: utf-8 -*-
"""应用工厂。

构造 FastAPI 实例：挂中间件、注册异常处理器、注册全部路由、挂静态资源。

启动方式（与原 ``backend.app:app`` 等价）::

    uvicorn backend.app.main:app --host 0.0.0.0 --port 8000

兼容性：``backend.app:app`` 仍然可用（``backend/app/__init__.py`` re-export
``app``）。
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.core.exceptions import register_exception_handlers
from app.core.lifespan import lifespan
from app.static_assets import CacheControlMiddleware, mount_static
from app.api.routers import (
    manifest as manifest_router,
    risk as risk_router,
    borehole as borehole_router,
    geophysics as geophysics_router,
    search as search_router,
    chat as chat_router,
    report as report_router,
    analytics as analytics_router,
    health as health_router,
)


def create_app() -> FastAPI:
    """构造并返回 FastAPI 应用实例。"""
    settings = get_settings()
    app = FastAPI(
        title=settings.app_name,
        version="2.0",
        description="多源勘察数据融合展示与风险证据链决策平台（分层重构版）",
        lifespan=lifespan,
    )

    # ---- 中间件 ----
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # 静态资源缓存头：必须在首次请求前注册（Starlette 会在首个请求冻结中间件栈）。
    # 后注册先执行：CacheControlMiddleware 比 CORS 更靠近应用，能拦截 StaticFiles
    # 产生的响应并注入 Cache-Control，从而让 echarts/three/leaflet 等 ~2MB 库在
    # 刷新时走浏览器缓存，秒开页面。
    app.add_middleware(CacheControlMiddleware)

    # ---- 异常处理 ----
    register_exception_handlers(app)

    # ---- 路由 ----
    app.include_router(manifest_router.router)
    app.include_router(risk_router.router)
    app.include_router(borehole_router.router)
    app.include_router(geophysics_router.router)
    app.include_router(search_router.router)
    app.include_router(chat_router.router)
    app.include_router(report_router.router)
    app.include_router(analytics_router.router)
    app.include_router(health_router.router)

    # ---- 静态资源 ----
    mount_static(app)

    return app


# 模块级单例（uvicorn 引用 ``backend.app.main:app`` 或 ``backend.app:app``）
app = create_app()


if __name__ == "__main__":
    import uvicorn

    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
