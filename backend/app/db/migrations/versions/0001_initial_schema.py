# -*- coding: utf-8 -*-
"""初始 schema：projects/routes/risk_objects/boreholes/geophysics_lines/report_sections/data_sources

Revision ID: 0001_initial
Revises:
Create Date: 2025-01-01 00:00:00

说明
----
- 依赖 PostGIS 扩展（geometry 列）。
- 空间索引使用 ``USING GIST``。
- 本迁移假设运行在 PostgreSQL + PostGIS 环境。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.types import UserDefinedType


class _Geometry(UserDefinedType):
    """PostGIS geometry 列类型（仅 DDL 用，避免引入 geoalchemy2 依赖）。"""

    cache_ok = True

    def __init__(self, geom_type: str, srid: int = 0) -> None:
        self.geom_type = geom_type
        self.srid = srid

    def get_col_spec(self, **_) -> str:
        return f"geometry({self.geom_type}, {self.srid})"

revision: str = "0001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- 启用 PostGIS ----
    op.execute('CREATE EXTENSION IF NOT EXISTS postgis;')
    op.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";')

    op.create_table(
        "projects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(64), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("subtitle", sa.String(255)),
        sa.Column("scenario", sa.Text()),
        sa.Column("coordinate_note", sa.Text()),
        sa.Column("mileage_note", sa.Text()),
        sa.Column("srid", sa.Integer(), server_default="0"),
        # extent_geom: PostGIS Polygon (SRID 0)
        sa.Column("extent_geom", _Geometry("Polygon", 0)),
    )
    op.create_index("ix_projects_code", "projects", ["code"], unique=True)

    op.create_table(
        "routes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("type", sa.String(32)),
        sa.Column("name", sa.String(255)),
        sa.Column("start_mileage", sa.String(16)),
        sa.Column("end_mileage", sa.String(16)),
        sa.Column("centerline_geom", _Geometry("LineString", 0)),
        sa.Column("portals_json", sa.Text().with_variant(
            sa.dialects.postgresql.JSONB(), "postgresql")),
    )
    op.create_index("ix_routes_project_id", "routes", ["project_id"])

    op.create_table(
        "geophysics_lines",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("method", sa.String(64)),
        sa.Column("length_m", sa.Numeric(), nullable=False),
        sa.Column("rho_min", sa.Numeric()),
        sa.Column("anomaly_depth_m", sa.Numeric()),
        sa.Column("image_path", sa.String(255)),
        sa.Column("csv_path", sa.String(255)),
        sa.Column("axis_geom", _Geometry("LineString", 0)),
    )
    op.create_index("ix_geophysics_lines_project_id",
                    "geophysics_lines", ["project_id"])

    op.create_table(
        "risk_objects",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("type", sa.String(64), nullable=False),
        sa.Column("type_cn", sa.String(64), nullable=False),
        sa.Column("risk_level", sa.String(16), nullable=False),
        sa.Column("confidence", sa.String(16)),
        sa.Column("mileage", sa.String(16), nullable=False),
        sa.Column("mileage_m", sa.Numeric(), nullable=False),
        sa.Column("center_geom", _Geometry("Point", 0)),
        sa.Column("polygon_geom", _Geometry("Polygon", 0)),
        sa.Column("borehole_ids", sa.Text().with_variant(
            sa.dialects.postgresql.ARRAY(sa.Text()), "postgresql")),
        sa.Column("geophysics_line_id", sa.String(16),
                  sa.ForeignKey("geophysics_lines.id")),
        sa.Column("evidence_json", sa.Text().with_variant(
            sa.dialects.postgresql.JSONB(), "postgresql")),
        sa.Column("interpretation", sa.Text()),
        sa.Column("design_suggestion", sa.Text()),
    )
    op.create_index("ix_risk_objects_project_id", "risk_objects", ["project_id"])
    op.create_index("ix_risk_objects_mileage_m", "risk_objects", ["mileage_m"])

    op.create_table(
        "boreholes",
        sa.Column("id", sa.String(16), primary_key=True),
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("mileage", sa.String(16), nullable=False),
        sa.Column("mileage_m", sa.Numeric()),
        sa.Column("depth_m", sa.Numeric(), nullable=False),
        sa.Column("elevation", sa.Numeric()),
        sa.Column("water_depth_m", sa.Numeric()),
        sa.Column("location_geom", _Geometry("Point", 0)),
        sa.Column("layers_json", sa.Text().with_variant(
            sa.dialects.postgresql.JSONB(), "postgresql")),
    )
    op.create_index("ix_boreholes_project_id", "boreholes", ["project_id"])

    op.create_table(
        "report_sections",
        sa.Column("id", sa.String(32), primary_key=True),
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("related_risks", sa.Text().with_variant(
            sa.dialects.postgresql.ARRAY(sa.Text()), "postgresql")),
    )
    op.create_index("ix_report_sections_project_id",
                    "report_sections", ["project_id"])

    op.create_table(
        "data_sources",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("project_id", sa.Integer(),
                  sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("file_path", sa.String(255)),
        sa.Column("meta_json", sa.Text().with_variant(
            sa.dialects.postgresql.JSONB(), "postgresql")),
    )
    op.create_index("ix_data_sources_project_id", "data_sources", ["project_id"])

    # ---- 空间索引（PostGIS GIST）----
    op.execute(
        "CREATE INDEX ix_projects_extent_gist ON projects "
        "USING GIST (extent_geom);"
    )
    op.execute(
        "CREATE INDEX ix_routes_centerline_gist ON routes "
        "USING GIST (centerline_geom);"
    )
    op.execute(
        "CREATE INDEX ix_risk_objects_center_gist ON risk_objects "
        "USING GIST (center_geom);"
    )
    op.execute(
        "CREATE INDEX ix_risk_objects_polygon_gist ON risk_objects "
        "USING GIST (polygon_geom);"
    )
    op.execute(
        "CREATE INDEX ix_boreholes_location_gist ON boreholes "
        "USING GIST (location_geom);"
    )
    op.execute(
        "CREATE INDEX ix_geophysics_axis_gist ON geophysics_lines "
        "USING GIST (axis_geom);"
    )


def downgrade() -> None:
    op.drop_table("data_sources")
    op.drop_table("report_sections")
    op.drop_table("boreholes")
    op.drop_table("risk_objects")
    op.drop_table("geophysics_lines")
    op.drop_table("routes")
    op.drop_table("projects")
