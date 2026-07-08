# -*- coding: utf-8 -*-
"""risk_objects 表（核心，设计文档 §6.1）。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, String, Text, Numeric, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base, JSONVariant, TextArrayVariant


class RiskObject(Base):
    __tablename__ = "risk_objects"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    type: Mapped[str] = mapped_column(String(64))
    type_cn: Mapped[str] = mapped_column(String(64))
    risk_level: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    mileage: Mapped[str] = mapped_column(String(16))
    mileage_m: Mapped[float] = mapped_column(Numeric, index=True)

    # center_geom / polygon_geom: PostGIS Point / Polygon (SRID 0)，由
    # seed 脚本以原生 SQL 写入（仅 PG 方言）；展示用坐标另存 JSON 列，
    # 保证 API 响应可从任意方言逐字节重建。
    center_xy: Mapped[Optional[list]] = mapped_column(JSONVariant, nullable=True)
    polygon_xy: Mapped[Optional[list]] = mapped_column(JSONVariant, nullable=True)
    borehole_ids: Mapped[list] = mapped_column(TextArrayVariant, default=list)
    geophysics_line_id: Mapped[Optional[str]] = mapped_column(
        String(16), ForeignKey("geophysics_lines.id"), nullable=True)
    evidence_json: Mapped[dict] = mapped_column(JSONVariant, default=dict)
    interpretation: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    design_suggestion: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
