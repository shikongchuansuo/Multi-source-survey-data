# -*- coding: utf-8 -*-
"""静态资源挂载。

对应原 ``app.py`` 的 ``app.mount(...)`` 与根路径 ``/`` 行为，路径完全一致：
- ``/ui``     → ``frontend/``  (html=True)
- ``/static`` → ``frontend/static/``
- ``/lib``    → ``frontend/static/lib/``
- ``/data``   → ``backend/data/``
- ``/``       → 返回 ``frontend/index.html``
"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.core.config import get_settings


def mount_static(app: FastAPI) -> None:
    """挂载静态资源与首页路由。"""
    s = get_settings()
    frontend = s.frontend_dir
    static = frontend / "static"
    lib = static / "lib"
    data = s.data_dir

    app.mount("/ui", StaticFiles(directory=str(frontend), html=True), name="ui")
    app.mount("/static", StaticFiles(directory=str(static)), name="static")
    app.mount("/lib", StaticFiles(directory=str(lib)), name="lib")
    app.mount("/data", StaticFiles(directory=str(data)), name="data")

    @app.get("/", include_in_schema=False)
    def index():
        """根路径返回前端首页。"""
        return FileResponse(str(frontend / "index.html"))
