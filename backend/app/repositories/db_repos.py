# -*- coding: utf-8 -*-
"""数据库源 repository 实现（``use_db=True`` 模式）。

设计要点
--------
- 继承对应的文件源 repo，仅重写数据装载方法（``_manifest`` / ``_risks``
  / ``_boreholes`` / ``_lines`` / ``_report``），查询方法逻辑完全复用，
  保证两种数据源下 service/API 行为一致。
- 从 ORM 行**重建与 ``backend/data/*.json`` 逐字段一致的 dict**（键集、
  嵌套结构相同；Numeric 统一转 float）——这是 API 兼容性红线在 DB
  模式下的保证，由 ``scripts/verify_api_equivalence.py`` A/B 验证。
- 物探 CSV 网格、栅格、点云仍走文件（设计文档 §六：DB 只存路径引用），
  故 ``read_grid_rows`` 直接继承文件实现。
- 方言无关：PostgreSQL（JSONB + PostGIS）与 SQLite（JSON，单机演示/
  本地验证）均可作为后端。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List, Optional

from app.repositories.file_repos import (
    ManifestFileRepo,
    RiskFileRepo,
    BoreholeFileRepo,
    GeophysicsFileRepo,
    ReportFileRepo,
)


def _num(v) -> Optional[float]:
    """Numeric 列（Decimal）→ float；None 保持 None。"""
    return None if v is None else float(v)


def _fetch_all(model, order_by=None) -> list:
    from app.db.session import get_session
    with get_session() as session:
        q = session.query(model)
        if order_by is not None:
            q = q.order_by(order_by)
        rows = q.all()
        session.expunge_all()
        return rows


class ManifestDbRepo(ManifestFileRepo):
    """manifest 由 projects/routes/risk_objects/data_sources 表重建。"""

    @lru_cache(maxsize=1)
    def _manifest(self) -> Dict[str, Any]:
        from app.models.orm import Project, Route, DataSource

        proj = _fetch_all(Project)[0]
        route = _fetch_all(Route)[0]
        assets = dict(proj.assets_json or {})
        assets.pop("report_meta", None)

        route_dict: Dict[str, Any] = {
            "type": route.type,
            "name": route.name,
            "start_mileage": route.start_mileage,
            "end_mileage": route.end_mileage,
        }
        route_dict.update(route.portals_json or {})
        route_dict["centerline"] = route.centerline_json

        return {
            "project": {
                "name": proj.name,
                "subtitle": proj.subtitle,
                "scenario": proj.scenario,
                "coordinate_note": proj.coordinate_note,
                "mileage_note": proj.mileage_note,
            },
            "route": route_dict,
            **assets,
            "risk_objects": RiskDbRepo(self.store).all_risks(),
            "data_sources": [
                ds.meta_json for ds in _fetch_all(DataSource)
            ],
        }


class RiskDbRepo(RiskFileRepo):

    @lru_cache(maxsize=1)
    def _risks(self) -> List[Dict[str, Any]]:
        from app.models.orm import RiskObject

        return [{
            "id": r.id,
            "name": r.name,
            "mileage": r.mileage,
            "mileage_m": _num(r.mileage_m),
            "type": r.type,
            "type_cn": r.type_cn,
            "risk_level": r.risk_level,
            "confidence": r.confidence,
            "polygon_xy": r.polygon_xy,
            "center_xy": r.center_xy,
            "evidence": r.evidence_json,
            "interpretation": r.interpretation,
            "design_suggestion": r.design_suggestion,
            "geophysics_line": r.geophysics_line_id,
            "borehole_ids": list(r.borehole_ids or []),
        } for r in _fetch_all(RiskObject, RiskObject.id)]


class BoreholeDbRepo(BoreholeFileRepo):

    @lru_cache(maxsize=1)
    def _boreholes(self) -> List[Dict[str, Any]]:
        from app.models.orm import Borehole

        return [{
            "id": b.id,
            "xy": b.xy,
            "mileage": b.mileage,
            "elevation": _num(b.elevation),
            "depth_m": _num(b.depth_m),
            "water_depth_m": _num(b.water_depth_m),
            "layers": b.layers_json,
        } for b in _fetch_all(Borehole, Borehole.id)]


class GeophysicsDbRepo(GeophysicsFileRepo):

    @lru_cache(maxsize=1)
    def _lines(self) -> List[Dict[str, Any]]:
        from app.models.orm import GeophysicsLine

        return [{
            "id": g.id,
            "name": g.name,
            "related_risk": g.related_risk,
            "start_xy": g.start_xy,
            "end_xy": g.end_xy,
            "length_m": _num(g.length_m),
            "method": g.method,
            "rho_min": _num(g.rho_min),
            "anomaly_depth_m": _num(g.anomaly_depth_m),
            "image": g.image_path,
            "csv": g.csv_path,
        } for g in _fetch_all(GeophysicsLine, GeophysicsLine.id)]

    # read_grid_rows 继承文件实现（CSV 仍走文件，DB 只存路径）


class ReportDbRepo(ReportFileRepo):

    @lru_cache(maxsize=1)
    def _report(self) -> Dict[str, Any]:
        from app.models.orm import Project, ReportSection

        proj = _fetch_all(Project)[0]
        meta = (proj.assets_json or {}).get("report_meta", {})
        sections = []
        for s in _fetch_all(ReportSection, ReportSection.id):
            d: Dict[str, Any] = {"id": s.id, "title": s.title,
                                 "content": s.content}
            # 源 JSON 仅在非空时携带 related_risks 键
            if s.related_risks:
                d["related_risks"] = list(s.related_risks)
            sections.append(d)
        return {**meta, "sections": sections}


__all__ = [
    "ManifestDbRepo", "RiskDbRepo", "BoreholeDbRepo",
    "GeophysicsDbRepo", "ReportDbRepo",
]
