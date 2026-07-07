# -*- coding: utf-8 -*-
"""ORM 基类与声明式映射基础。

使用 SQLAlchemy 2.0 风格的 ``DeclarativeBase``。
geometry 列由 GeoAlchemy2 提供（``use_db=True`` 时才需要该依赖）。
"""
from __future__ import annotations

from sqlalchemy import JSON, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase

# 跨方言类型：PostgreSQL 用 JSONB / text[]，其他方言（如 SQLite 单机
# 演示/本地验证）退化为 JSON。保证 use_db=True 不强绑 PG。
JSONVariant = JSON().with_variant(JSONB(), "postgresql")
TextArrayVariant = JSON().with_variant(ARRAY(Text()), "postgresql")


class Base(DeclarativeBase):
    """所有 ORM 模型的基类。"""
    pass
