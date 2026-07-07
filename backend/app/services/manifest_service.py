# -*- coding: utf-8 -*-
"""项目总览业务。

对应原 ``app.py::get_manifest``。返回项目元信息、线路、数据源清单、
风险对象摘要、统计数据。

输出结构与重构前**逐字段一致**。
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.repositories import (
    get_manifest_repo, get_risk_repo, get_borehole_repo,
    get_geophysics_repo, get_report_repo,
)


class ManifestService:
    def __init__(self) -> None:
        self.manifest_repo = get_manifest_repo()
        self.risk_repo = get_risk_repo()
        self.borehole_repo = get_borehole_repo()
        self.geophysics_repo = get_geophysics_repo()
        self.report_repo = get_report_repo()

    def get_manifest(self) -> Dict[str, Any]:
        m = self.manifest_repo.get_manifest()
        risks: List[Dict[str, Any]] = []
        for r in m["risk_objects"]:
            risks.append({
                "id": r["id"], "name": r["name"], "mileage": r["mileage"],
                "type": r["type"], "type_cn": r["type_cn"],
                "risk_level": r["risk_level"], "confidence": r["confidence"],
                "center_xy": r["center_xy"], "polygon_xy": r["polygon_xy"],
                "borehole_ids": r.get("borehole_ids", []),
                "geophysics_line": r.get("geophysics_line"),
            })
        return {
            "project": m["project"],
            "route": m["route"],
            "data_sources": m["data_sources"],
            "dem": m["dem"], "orthophoto": m["orthophoto"],
            "pointcloud": m["pointcloud"],
            "risks": risks,
            "stats": {
                "risk_count": len(risks),
                "borehole_count": len(self.borehole_repo.all_boreholes()),
                "geophysics_lines": len(self.geophysics_repo.all_lines()),
                "report_sections": len(self.report_repo.sections()),
            },
        }
