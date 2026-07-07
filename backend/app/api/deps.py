# -*- coding: utf-8 -*-
"""依赖注入入口。

供 routers 通过 ``Depends`` 获取 service。集中在此便于测试时替换 mock。
"""
from __future__ import annotations

from app.services import (
    get_manifest_service, get_risk_service, get_borehole_service,
    get_geophysics_service, get_search_service, get_analytics_service,
    get_chat_service, get_report_service,
)

__all__ = [
    "get_manifest_service", "get_risk_service", "get_borehole_service",
    "get_geophysics_service", "get_search_service", "get_analytics_service",
    "get_chat_service", "get_report_service",
]
