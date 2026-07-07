# -*- coding: utf-8 -*-
"""检索路由 ``/api/search``。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_search_service
from app.services.search_service import SearchService

router = APIRouter()


@router.get("/api/search")
def search(q: str = Query(..., description="关键词"),
           svc: SearchService = Depends(get_search_service)):
    """关键词检索（风险对象 + 报告段落）。"""
    return svc.search(q)
