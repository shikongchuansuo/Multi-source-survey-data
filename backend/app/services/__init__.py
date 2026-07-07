# -*- coding: utf-8 -*-
"""业务层。

承载原 ``backend/app.py`` 的全部业务逻辑（证据卡组装、多维评分、物探网格
构建、问答模板、对话调度）。**不 import fastapi**，便于单测。

访问方式：通过 ``get_*_service()`` 工厂获取。
"""
from __future__ import annotations

from app.services.factory import (
    get_manifest_service,
    get_risk_service,
    get_borehole_service,
    get_geophysics_service,
    get_search_service,
    get_analytics_service,
    get_chat_service,
    get_report_service,
)

__all__ = [
    "get_manifest_service", "get_risk_service", "get_borehole_service",
    "get_geophysics_service", "get_search_service", "get_analytics_service",
    "get_chat_service", "get_report_service",
]
