# -*- coding: utf-8 -*-
"""健康检查路由 ``/api/health``。"""
from __future__ import annotations

from fastapi import APIRouter

from app.core.config import get_settings
from app.repositories import get_risk_repo, get_borehole_repo

router = APIRouter()


@router.get("/api/health")
def health():
    # 响应字段与重构前 app.py 完全一致（use_db 不暴露给客户端）
    settings = get_settings()
    return {
        "status": "ok",
        "data_root": str(settings.data_dir),
        "risk_count": len(get_risk_repo().all_risks()),
        "borehole_count": len(get_borehole_repo().all_boreholes()),
        "report_formats": ["docx", "md", "html"],
    }
