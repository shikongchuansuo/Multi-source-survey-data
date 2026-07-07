# -*- coding: utf-8 -*-
"""Repository 工厂。

根据 ``settings.use_db`` 选择 PG 源或文件源 repository。
设计文档 §八"双源过渡"策略的入口。

当前阶段（重构期）：``use_db=False`` 默认走文件源，保证行为与重构前一致。
PG 源 repository 在 Step 3/6 接入后通过本工厂切换。
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.repositories.file_repos import (
    ManifestFileRepo,
    RiskFileRepo,
    BoreholeFileRepo,
    GeophysicsFileRepo,
    ReportFileRepo,
)
from app.repositories.search_repo import SearchRepo


@lru_cache(maxsize=1)
def get_manifest_repo():
    return ManifestFileRepo()


@lru_cache(maxsize=1)
def get_risk_repo():
    return RiskFileRepo()


@lru_cache(maxsize=1)
def get_borehole_repo():
    return BoreholeFileRepo()


@lru_cache(maxsize=1)
def get_geophysics_repo():
    return GeophysicsFileRepo()


@lru_cache(maxsize=1)
def get_report_repo():
    return ReportFileRepo()


@lru_cache(maxsize=1)
def get_search_repo() -> SearchRepo:
    return SearchRepo(
        risk_repo=get_risk_repo(),      # type: ignore[arg-type]
        report_repo=get_report_repo(),  # type: ignore[arg-type]
    )


def reset_repos() -> None:
    """清除缓存（测试用）。"""
    get_manifest_repo.cache_clear()
    get_risk_repo.cache_clear()
    get_borehole_repo.cache_clear()
    get_geophysics_repo.cache_clear()
    get_report_repo.cache_clear()
    get_search_repo.cache_clear()


__all__ = [
    "get_manifest_repo", "get_risk_repo", "get_borehole_repo",
    "get_geophysics_repo", "get_report_repo", "get_search_repo",
    "reset_repos",
]
