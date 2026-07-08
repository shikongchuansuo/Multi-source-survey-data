# -*- coding: utf-8 -*-
"""Repository 工厂。

根据 ``settings.use_db`` 选择 DB 源或文件源 repository，是设计文档
§八"双源过渡"策略的入口。

选择规则
--------
- ``use_db=False``：文件源（= 重构前行为，run.bat 离线兜底）。
- ``use_db=True``：DB 源；构造时做一次**探测读取**，失败（DB 未启动、
  未 seed 等）则记录告警并回退文件源 —— 演示永不翻车。

DB 源与文件源接口完全一致（DB repo 继承文件 repo，仅重写装载），
上层 service 无感知。
"""
from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.core.logging import get_logger
from app.repositories.file_repos import (
    ManifestFileRepo,
    RiskFileRepo,
    BoreholeFileRepo,
    GeophysicsFileRepo,
    ReportFileRepo,
)
from app.repositories.search_repo import SearchRepo

_log = get_logger(__name__)


def _pick(file_cls, db_cls_name: str, probe: str):
    """按配置实例化 repo：DB 源探测失败回退文件源。

    ``probe`` 为装载方法名（如 ``_risks``），构造后立即调用一次以验证
    DB 可用且已 seed；lru_cache 保证探测结果被缓存、不重复查询。
    """
    settings = get_settings()
    if settings.use_db:
        try:
            from app.repositories import db_repos
            repo = getattr(db_repos, db_cls_name)()
            getattr(repo, probe)()  # 探测读取
            return repo
        except Exception as exc:  # noqa: BLE001
            _log.warning("DB 源 {} 不可用，回退文件源：{}", db_cls_name, exc)
    return file_cls()


@lru_cache(maxsize=1)
def get_manifest_repo():
    return _pick(ManifestFileRepo, "ManifestDbRepo", "_manifest")


@lru_cache(maxsize=1)
def get_risk_repo():
    return _pick(RiskFileRepo, "RiskDbRepo", "_risks")


@lru_cache(maxsize=1)
def get_borehole_repo():
    return _pick(BoreholeFileRepo, "BoreholeDbRepo", "_boreholes")


@lru_cache(maxsize=1)
def get_geophysics_repo():
    return _pick(GeophysicsFileRepo, "GeophysicsDbRepo", "_lines")


@lru_cache(maxsize=1)
def get_report_repo():
    return _pick(ReportFileRepo, "ReportDbRepo", "_report")


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
