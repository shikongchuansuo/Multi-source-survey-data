# -*- coding: utf-8 -*-
"""补充展示用字段：API 逐字节重建所需的 JSON 坐标列与资产引用。

Revision ID: 0002_display_fields
Revises: 0001_initial

说明
----
PostGIS geometry 列服务空间查询；前端展示所需的原始坐标
（center_xy/polygon_xy/xy/start_xy/end_xy/centerline）以 JSONB 冗余
存储，保证 DB 模式下 API 响应与文件模式逐字节一致（兼容性红线）。
"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision: str = "0002_display_fields"
down_revision: Union[str, None] = "0001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("assets_json", JSONB(), nullable=True))
    op.add_column("routes", sa.Column("centerline_json", JSONB(), nullable=True))
    op.add_column("risk_objects", sa.Column("center_xy", JSONB(), nullable=True))
    op.add_column("risk_objects", sa.Column("polygon_xy", JSONB(), nullable=True))
    op.add_column("boreholes", sa.Column("xy", JSONB(), nullable=True))
    op.add_column("geophysics_lines",
                  sa.Column("related_risk", sa.String(16), nullable=True))
    op.add_column("geophysics_lines", sa.Column("start_xy", JSONB(), nullable=True))
    op.add_column("geophysics_lines", sa.Column("end_xy", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("geophysics_lines", "end_xy")
    op.drop_column("geophysics_lines", "start_xy")
    op.drop_column("geophysics_lines", "related_risk")
    op.drop_column("boreholes", "xy")
    op.drop_column("risk_objects", "polygon_xy")
    op.drop_column("risk_objects", "center_xy")
    op.drop_column("routes", "centerline_json")
    op.drop_column("projects", "assets_json")
