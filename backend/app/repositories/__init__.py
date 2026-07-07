# -*- coding: utf-8 -*-
"""数据访问层。

封装两类数据源：
1. **元数据 + 空间要素**：``use_db=True`` 时走 PostgreSQL/PostGIS，
   ``use_db=False`` 时回退到 JSON 文件（双源过渡策略，见设计文档 §八）。
2. **栅格 / 点云 / CSV**：始终走 ``FileStore``（不进数据库）。

对外通过 ``get_*_repo()`` 工厂获取，业务层不感知数据来源。
"""
from __future__ import annotations

from app.repositories.factory import (
    get_manifest_repo,
    get_risk_repo,
    get_borehole_repo,
    get_geophysics_repo,
    get_report_repo,
    get_search_repo,
)

__all__ = [
    "get_manifest_repo", "get_risk_repo", "get_borehole_repo",
    "get_geophysics_repo", "get_report_repo", "get_search_repo",
]
