# -*- coding: utf-8 -*-
"""钻孔路由 ``/api/boreholes``。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_borehole_service
from app.services.borehole_service import BoreholeService

router = APIRouter()


@router.get("/api/boreholes")
def get_boreholes(bid: Optional[str] = Query(default=None),
                  svc: BoreholeService = Depends(get_borehole_service)):
    """钻孔列表或单钻孔详情。"""
    return svc.list_or_get(bid)
