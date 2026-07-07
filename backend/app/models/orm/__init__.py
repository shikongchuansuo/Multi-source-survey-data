# -*- coding: utf-8 -*-
"""SQLAlchemy ORM 映射。

仅在 ``use_db=True``（PostgreSQL 模式）下使用。所有表见设计文档 §六。

注意：``geometry`` 列依赖 PostGIS。Alembic 初始迁移（``db/migrations/``）
负责建表与空间索引。
"""
from __future__ import annotations

from app.models.orm.base import Base
from app.models.orm.project import Project, Route
from app.models.orm.risk import RiskObject
from app.models.orm.borehole import Borehole
from app.models.orm.geophysics import GeophysicsLine
from app.models.orm.report import ReportSection, DataSource

__all__ = [
    "Base",
    "Project", "Route", "RiskObject", "Borehole",
    "GeophysicsLine", "ReportSection", "DataSource",
]
