# -*- coding: utf-8 -*-
"""数据装载脚本：把 ``backend/data/*.json`` 装入 PostgreSQL。

幂等：可重复运行（基于主键 upsert）。

用法::

    # 先确保 PG 已启动 + 迁移已执行
    set FUSION_USE_DB=true
    set FUSION_DATABASE_URL=postgresql+psycopg://fusion:fusion@localhost:5432/fusion
    python -m backend.scripts.seed

注意：此脚本仅在 ``use_db=True`` 时有意义。
"""
from __future__ import annotations

import sys
from pathlib import Path

# 确保仓库根在 sys.path
_HERE = Path(__file__).resolve().parent
_BACKEND = _HERE.parent           # backend/
_ROOT = _BACKEND.parent           # 仓库根
for p in (str(_ROOT), str(_BACKEND)):
    if p not in sys.path:
        sys.path.insert(0, p)

import json  # noqa: E402

from sqlalchemy import create_engine, text  # noqa: E402


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    # 延迟导入，避免无 sqlalchemy 环境下 import 失败
    try:
        from app.core.config import get_settings
        from app.models.orm import (
            Base, Project, Route, RiskObject, Borehole,
            GeophysicsLine, ReportSection, DataSource,
        )
        from sqlalchemy.orm import Session
    except ImportError as exc:
        print(f"[seed] 缺少依赖：{exc}")
        print("[seed] 请先 pip install SQLAlchemy geoalchemy2 psycopg[binary]")
        return 2

    settings = get_settings()
    if not settings.database_url:
        print("[seed] 未配置 database_url")
        return 2

    data_dir = settings.data_dir
    print(f"[seed] 数据目录: {data_dir}")
    print(f"[seed] 数据库  : {settings.database_url}")

    engine = create_engine(settings.database_url, future=True)
    is_pg = engine.dialect.name == "postgresql"

    # 启用 PostGIS 扩展（幂等，仅 PG）
    if is_pg:
        with engine.connect() as conn:
            conn.execute(text('CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'))
            try:
                conn.execute(text('CREATE EXTENSION IF NOT EXISTS postgis;'))
            except Exception as exc:  # noqa: BLE001
                print(f"[seed] 警告：PostGIS 扩展不可用：{exc}")
            conn.commit()

    # 建表（开发期便捷；正式用 Alembic 迁移）
    Base.metadata.create_all(engine)

    manifest = load_json(data_dir / "manifest.json")
    boreholes = load_json(data_dir / "boreholes" / "boreholes.json")
    geo_lines = load_json(data_dir / "geophysics" / "lines.json")
    report = load_json(data_dir / "report" / "survey_report.json")

    with Session(engine) as session:
        # ---- project ----
        proj = session.get(Project, 1) or Project(id=1)
        proj.code = "XX_TUNNEL_K12"
        proj.name = manifest["project"]["name"]
        proj.subtitle = manifest["project"].get("subtitle")
        proj.scenario = manifest["project"].get("scenario")
        proj.coordinate_note = manifest["project"].get("coordinate_note")
        proj.mileage_note = manifest["project"].get("mileage_note")
        proj.srid = 0
        proj.assets_json = {
            k: manifest[k]
            for k in ("dem", "orthophoto", "pointcloud",
                      "boreholes", "geophysics_lines", "report")
            if k in manifest
        }
        # 报告顶层元数据（DB 模式重建 survey_report 用）
        proj.assets_json["report_meta"] = {
            k: report[k]
            for k in ("title", "project", "survey_unit", "date")
            if k in report
        }
        session.add(proj)

        # ---- route ----
        route = session.query(Route).filter_by(project_id=1).first()
        r = manifest["route"]
        if route is None:
            route = Route(project_id=1)
        route.type = r.get("type")
        route.name = r.get("name")
        route.start_mileage = r.get("start_mileage")
        route.end_mileage = r.get("end_mileage")
        route.centerline_json = r.get("centerline")
        route.portals_json = {
            "portal_in": r.get("portal_in"),
            "portal_out": r.get("portal_out"),
        }
        session.add(route)

        # ---- risks ----
        for rk in manifest["risk_objects"]:
            obj = session.get(RiskObject, rk["id"]) or RiskObject(id=rk["id"])
            obj.project_id = 1
            obj.name = rk["name"]
            obj.type = rk["type"]
            obj.type_cn = rk["type_cn"]
            obj.risk_level = rk["risk_level"]
            obj.confidence = rk.get("confidence")
            obj.mileage = rk["mileage"]
            obj.mileage_m = rk["mileage_m"]
            obj.center_xy = rk.get("center_xy")
            obj.polygon_xy = rk.get("polygon_xy")
            obj.borehole_ids = rk.get("borehole_ids", [])
            obj.geophysics_line_id = rk.get("geophysics_line")
            obj.evidence_json = rk.get("evidence", {})
            obj.interpretation = rk.get("interpretation")
            obj.design_suggestion = rk.get("design_suggestion")
            session.add(obj)

        # ---- boreholes ----
        for b in boreholes:
            obj = session.get(Borehole, b["id"]) or Borehole(id=b["id"])
            obj.project_id = 1
            obj.mileage = b.get("mileage", "")
            obj.mileage_m = _mileage_to_m(b.get("mileage", ""))
            obj.depth_m = b.get("depth_m", 0)
            obj.elevation = b.get("elevation")
            obj.water_depth_m = b.get("water_depth_m")
            obj.xy = b.get("xy")
            obj.layers_json = b.get("layers", [])
            session.add(obj)

        # ---- geophysics ----
        for g in geo_lines:
            obj = session.get(GeophysicsLine, g["id"]) or GeophysicsLine(id=g["id"])
            obj.project_id = 1
            obj.name = g.get("name", g["id"])
            obj.method = g.get("method")
            obj.length_m = g.get("length_m", 0)
            obj.rho_min = g.get("rho_min")
            obj.anomaly_depth_m = g.get("anomaly_depth_m")
            obj.image_path = g.get("image")
            obj.csv_path = g.get("csv")
            obj.related_risk = g.get("related_risk")
            obj.start_xy = g.get("start_xy")
            obj.end_xy = g.get("end_xy")
            session.add(obj)

        # ---- report sections ----
        for s in report.get("sections", []):
            obj = session.get(ReportSection, s["id"]) or ReportSection(id=s["id"])
            obj.project_id = 1
            obj.title = s.get("title", "")
            obj.content = s.get("content", "")
            obj.related_risks = s.get("related_risks", [])
            session.add(obj)

        # ---- data sources ----
        session.query(DataSource).filter_by(project_id=1).delete()
        for i, ds in enumerate(manifest.get("data_sources", [])):
            session.add(DataSource(
                id=i + 1, project_id=1,
                name=ds.get("type", ""), kind=ds.get("icon", ""),
                file_path=ds.get("file"), meta_json=ds,
            ))

        session.commit()

    # ---- PostGIS 几何列（空间查询能力，仅 PG）----
    if is_pg:
        _seed_geometries(engine)

    print("[seed] 装载完成 ✓")
    return 0


def _seed_geometries(engine) -> None:
    """从 JSON 坐标列生成 PostGIS geometry（幂等）。"""
    from sqlalchemy import text as _t
    stmts = [
        # 风险中心点 / 边界多边形
        """UPDATE risk_objects SET center_geom = ST_SetSRID(ST_MakePoint(
               (center_xy->>0)::float, (center_xy->>1)::float), 0)
           WHERE center_xy IS NOT NULL""",
        """UPDATE risk_objects SET polygon_geom = (
               SELECT ST_SetSRID(ST_MakePolygon(ST_MakeLine(
                   pt || ARRAY[(SELECT p FROM (
                       SELECT ST_MakePoint((e->>0)::float,(e->>1)::float) AS p
                       FROM jsonb_array_elements(polygon_xy) WITH ORDINALITY t(e,i)
                       ORDER BY i LIMIT 1) f)]
               )), 0)
               FROM (SELECT array_agg(
                       ST_MakePoint((e->>0)::float,(e->>1)::float) ORDER BY i) AS pt
                     FROM jsonb_array_elements(polygon_xy) WITH ORDINALITY t(e,i)) s
           ) WHERE polygon_xy IS NOT NULL""",
        # 钻孔孔口点
        """UPDATE boreholes SET location_geom = ST_SetSRID(ST_MakePoint(
               (xy->>0)::float, (xy->>1)::float), 0)
           WHERE xy IS NOT NULL""",
        # 测线轴线
        """UPDATE geophysics_lines SET axis_geom = ST_SetSRID(ST_MakeLine(
               ST_MakePoint((start_xy->>0)::float,(start_xy->>1)::float),
               ST_MakePoint((end_xy->>0)::float,(end_xy->>1)::float)), 0)
           WHERE start_xy IS NOT NULL AND end_xy IS NOT NULL""",
        # 线路中心线
        """UPDATE routes SET centerline_geom = (
               SELECT ST_SetSRID(ST_MakeLine(
                   ST_MakePoint((e->>0)::float,(e->>1)::float) ORDER BY i), 0)
               FROM jsonb_array_elements(centerline_json) WITH ORDINALITY t(e,i)
           ) WHERE centerline_json IS NOT NULL""",
    ]
    with engine.connect() as conn:
        for s in stmts:
            try:
                conn.execute(_t(s))
            except Exception as exc:  # noqa: BLE001
                print(f"[seed] 警告：geometry 写入失败（不影响 API）：{exc}")
        conn.commit()


def _mileage_to_m(mileage: str) -> float | None:
    import re
    m = re.search(r"K12\+?(\d{3})", mileage or "")
    return float(12000 + int(m.group(1))) if m else None


if __name__ == "__main__":
    raise SystemExit(main())
