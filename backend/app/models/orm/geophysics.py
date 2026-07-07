# -*- coding: utf-8 -*-
"""geophysics_lines 表（设计文档 §6.1）。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, String, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base, JSONVariant


class GeophysicsLine(Base):
    __tablename__ = "geophysics_lines"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(255))
    method: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    length_m: Mapped[float] = mapped_column(Numeric)
    rho_min: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    anomaly_depth_m: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    image_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    csv_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # axis_geom: PostGIS LineString (SRID 0)；展示用端点坐标另存 JSON 列
    related_risk: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    start_xy: Mapped[Optional[list]] = mapped_column(JSONVariant, nullable=True)
    end_xy: Mapped[Optional[list]] = mapped_column(JSONVariant, nullable=True)
