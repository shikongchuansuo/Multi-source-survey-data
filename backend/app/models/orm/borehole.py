# -*- coding: utf-8 -*-
"""boreholes 表（设计文档 §6.1）。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, String, Numeric, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base, JSONVariant


class Borehole(Base):
    __tablename__ = "boreholes"

    id: Mapped[str] = mapped_column(String(16), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    mileage: Mapped[str] = mapped_column(String(16))
    mileage_m: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    depth_m: Mapped[float] = mapped_column(Numeric)
    elevation: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    water_depth_m: Mapped[Optional[float]] = mapped_column(Numeric, nullable=True)
    # location_geom: PostGIS Point (SRID 0)；展示用孔口坐标另存 JSON 列
    xy: Mapped[Optional[list]] = mapped_column(JSONVariant, nullable=True)
    layers_json: Mapped[list] = mapped_column(JSONVariant, default=list)
