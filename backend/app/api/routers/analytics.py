# -*- coding: utf-8 -*-
"""分析路由：沿线剖面 + 三维结构 + DEM 地形网格。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.deps import get_analytics_service
from app.services.analytics_service import AnalyticsService

router = APIRouter()


@router.get("/api/profile/route")
def get_route_profile(svc: AnalyticsService = Depends(get_analytics_service)):
    """沿线路地质纵剖面。"""
    return svc.get_route_profile()


@router.get("/api/3d/structures")
def get_3d_structures(svc: AnalyticsService = Depends(get_analytics_service)):
    """三维地质结构数据。"""
    return svc.get_3d_structures()


@router.get("/api/3d/sections")
def get_3d_sections(svc: AnalyticsService = Depends(get_analytics_service)):
    """物探测线三维帷幕面（电阻率断面随地形展开）。"""
    return svc.get_3d_sections()


@router.get("/api/3d/voxel")
def get_3d_voxel(svc: AnalyticsService = Depends(get_analytics_service)):
    """三维体素地质模型（交付数据优先，缺省用演示模型）。"""
    return svc.get_3d_voxel()


@router.get("/api/3d/terrain")
def get_3d_terrain(step: int = 4,
                   svc: AnalyticsService = Depends(get_analytics_service)):
    """DEM 地形网格（降采样）。"""
    return svc.get_3d_terrain(step)
