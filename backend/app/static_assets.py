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
from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.config import get_settings


def _cache_control(path: str) -> str | None:
    """按路径前缀返回 Cache-Control 值；None 表示该响应不加头。

    分类策略（命中"刷新秒开"且避免改坏前端代码）：
      /lib/  第三方库(echarts/three/leaflet，约 2MB，版本稳定) → 长缓存 + immutable
      /static/ 应用自有静态(app.js/app.css，无哈希) → 协商缓存，
              即 max-age=0 + must-revalidate，改动总能在刷新时生效
      /data/  勘察数据资源(PLY/PNG/CSV，运行期不变) → 长缓存
      其它(含 / 与 /api/) → 不加，默认每次获取，保证首页与 API 实时
    """
    if path.startswith("/lib/"):
        return "public, max-age=604800, immutable"   # 7 天
    if path.startswith("/data/"):
        return "public, max-age=604800"               # 7 天
    if path.startswith("/static/"):
        return "public, max-age=0, must-revalidate"   # 靠 ETag 协商
    return None


class CacheControlMiddleware:
    """为静态资源响应注入 Cache-Control 头的纯 ASGI 中间件。

    用原生 ASGI（而非 BaseHTTPMiddleware）实现：StaticFiles 的文件响应是流式
    分块发送的，BaseHTTPMiddleware 会把整段响应缓存进内存再转发，对 2.7MB 的
    点云 PLY 这类大文件既慢又费内存；原生 ASGI 逐 message 透传，无此问题。
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        cc = _cache_control(scope.get("path", ""))
        if cc is None:
            await self.app(scope, receive, send)
            return

        async def send_with_header(message):
            # 仅在响应头阶段追加，body 分块原样透传（不缓存进内存）
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                headers.append((b"cache-control", cc.encode("latin-1")))
                message = {**message, "headers": headers}
            await send(message)

        await self.app(scope, receive, send_with_header)


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
