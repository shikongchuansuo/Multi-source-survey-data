# -*- coding: utf-8 -*-
"""Service 工厂。缓存单例，业务层不直接 new。"""
from __future__ import annotations

from functools import lru_cache

from app.services.manifest_service import ManifestService
from app.services.risk_service import RiskService
from app.services.borehole_service import BoreholeService
from app.services.geophysics_service import GeophysicsService
from app.services.search_service import SearchService
from app.services.analytics_service import AnalyticsService
from app.services.chat_service import ChatService
from app.services.report_service import ReportService


@lru_cache(maxsize=1)
def get_manifest_service() -> ManifestService:
    return ManifestService()


@lru_cache(maxsize=1)
def get_risk_service() -> RiskService:
    return RiskService()


@lru_cache(maxsize=1)
def get_borehole_service() -> BoreholeService:
    return BoreholeService()


@lru_cache(maxsize=1)
def get_geophysics_service() -> GeophysicsService:
    return GeophysicsService()


@lru_cache(maxsize=1)
def get_search_service() -> SearchService:
    return SearchService()


@lru_cache(maxsize=1)
def get_analytics_service() -> AnalyticsService:
    return AnalyticsService()


@lru_cache(maxsize=1)
def get_chat_service() -> ChatService:
    return ChatService()


@lru_cache(maxsize=1)
def get_report_service() -> ReportService:
    return ReportService()


def reset_services() -> None:
    """清除缓存（测试用）。"""
    for fn in (get_manifest_service, get_risk_service, get_borehole_service,
               get_geophysics_service, get_search_service, get_analytics_service,
               get_chat_service, get_report_service):
        fn.cache_clear()
