# -*- coding: utf-8 -*-
"""projects / routes 表（设计文档 §6.1）。

工程局部坐标系 SRID 统一记为 0（自定义本地系）。
"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.orm.base import Base, JSONVariant

try:
    # PostGIS 几何列；无 geoalchemy2 时退化为 None，便于无 DB 环境下 import
    from geoalchemy2 import Geometry
    _HAS_GEO = True
except ImportError:  # pragma: no cover
    Geometry = None  # type: ignore[assignment]
    _HAS_GEO = False


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    subtitle: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    scenario: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    coordinate_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    mileage_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    srid: Mapped[int] = mapped_column(Integer, default=0)

    # manifest 中的资产路径引用（dem/orthophoto/pointcloud/boreholes/
    # geophysics_lines/report），DB 模式下重建 manifest 用
    assets_json: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)

    # extent_geom: PostGIS Polygon (SRID 0)
    # 仅在 geoalchemy2 可用时声明该列

    routes: Mapped[list["Route"]] = relationship(back_populates="project")

    def __repr__(self) -> str:
        return f"<Project {self.code}>"


class Route(Base):
    __tablename__ = "routes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    type: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    start_mileage: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    end_mileage: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    # centerline_geom: PostGIS LineString (SRID 0)，seed 以原生 SQL 写入；
    # 展示用中心线/洞口坐标另存 JSON 列
    centerline_json: Mapped[Optional[list]] = mapped_column(JSONVariant, nullable=True)
    portals_json: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)

    project: Mapped["Project"] = relationship(back_populates="routes")
