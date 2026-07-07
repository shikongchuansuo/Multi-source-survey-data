# -*- coding: utf-8 -*-
"""总览路由 ``/api/manifest``。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_manifest_service
from app.services.manifest_service import ManifestService

router = APIRouter()


@router.get("/api/manifest")
def get_manifest(svc: ManifestService = Depends(get_manifest_service)):
    """返回项目元信息、线路、数据源清单、风险对象摘要。"""
    return svc.get_manifest()
