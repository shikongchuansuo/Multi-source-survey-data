# -*- coding: utf-8 -*-
"""报告路由。

对应原 ``app.py``：
- ``GET /api/report``             报告能力总览
- ``GET /api/report/preview``     在线预览
- ``GET /api/report/download``    下载文件流（RFC 5987 中文文件名）
- ``GET /api/report/{rid}``       兼容旧接口（单风险 Markdown）

注意：``/api/report/{rid}`` 必须注册在 ``preview`` / ``download`` 之后，
否则 ``{rid}`` 会捕获 ``preview`` / ``download`` 路径段。
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from fastapi.responses import Response
from urllib.parse import quote

from app.api.deps import get_report_service
from app.services.report_service import ReportService

router = APIRouter()


@router.get("/api/report")
def report_overview(svc: ReportService = Depends(get_report_service)):
    """报告能力总览：列出可生成的报告与格式。"""
    return svc.overview()


@router.get("/api/report/preview")
def report_preview(scope: str = "full", rid: Optional[str] = None,
                   svc: ReportService = Depends(get_report_service)):
    """报告在线预览（返回 Markdown + HTML body）。"""
    return svc.preview(scope=scope, rid=rid)


@router.get("/api/report/download")
def report_download(scope: str = "full", rid: Optional[str] = None,
                    fmt: str = "docx",
                    svc: ReportService = Depends(get_report_service)):
    """报告下载（返回文件流）。中文文件名用 RFC 5987 编码。"""
    r = svc.generate(scope=scope, rid=rid, fmt=fmt)
    fname = r["filename"]
    ascii_fallback = "report." + fmt
    disposition = (
        f"attachment; filename=\"{ascii_fallback}\"; "
        f"filename*=UTF-8''{quote(fname)}"
    )
    return Response(
        content=r["content"],
        media_type=r["media_type"],
        headers={"Content-Disposition": disposition},
    )


@router.get("/api/report/{rid}")
def report_legacy(rid: str, download: int = 0,
                  svc: ReportService = Depends(get_report_service)):
    """兼容旧接口：单风险 Markdown 预览 / 下载。"""
    if download:
        r = svc.generate(scope="risk", rid=rid, fmt="md")
        fname = r["filename"]
        ascii_fallback = "report.md"
        disposition = (
            f"attachment; filename=\"{ascii_fallback}\"; "
            f"filename*=UTF-8''{quote(fname)}"
        )
        return Response(
            content=r["content"],
            media_type=r["media_type"],
            headers={"Content-Disposition": disposition},
        )
    return svc.preview(scope="risk", rid=rid)
