# -*- coding: utf-8 -*-
"""风险对象路由 ``/api/risk/{rid}``、``/api/risk_scores``。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.deps import get_risk_service, get_analytics_service
from app.services.risk_service import RiskService
from app.services.analytics_service import AnalyticsService

router = APIRouter()


@router.get("/api/risk/{rid}")
def get_risk(rid: str, svc: RiskService = Depends(get_risk_service)):
    """风险对象详情（多源证据）。"""
    return svc.get_risk(rid)


@router.get("/api/risk_scores")
def risk_scores(rid: Optional[str] = None,
                svc: AnalyticsService = Depends(get_analytics_service)):
    """风险多维评分，供 ECharts 雷达图。"""
    return svc.risk_scores(rid)
