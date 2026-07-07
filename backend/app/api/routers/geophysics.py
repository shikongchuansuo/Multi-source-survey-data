# -*- coding: utf-8 -*-
"""物探路由 ``/api/geophysics``、``/api/geophysics/{lid}/grid``。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_geophysics_service
from app.services.geophysics_service import GeophysicsService

router = APIRouter()


@router.get("/api/geophysics")
def get_geophysics(lid: Optional[str] = Query(default=None),
                   svc: GeophysicsService = Depends(get_geophysics_service)):
    """物探测线列表或单测线。"""
    return svc.list_or_get(lid)


@router.get("/api/geophysics/{lid}/grid")
def get_geophysics_grid(lid: str,
                        svc: GeophysicsService = Depends(get_geophysics_service)):
    """物探电阻率网格，供 ECharts 热力图。"""
    return svc.get_grid(lid)
