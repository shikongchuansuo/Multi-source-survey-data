# -*- coding: utf-8 -*-
"""风险对象业务（多源证据链）。

对应原 ``app.py::get_risk``：组装证据卡（影像→点云→物探→钻孔→报告）。

输出结构与重构前**逐字段一致**。
"""
from __future__ import annotations

from typing import Any, Dict

from app.core.exceptions import NotFoundError
from app.repositories import (
    get_risk_repo, get_borehole_repo, get_geophysics_repo,
    get_report_repo, get_manifest_repo,
)


class RiskService:
    def __init__(self) -> None:
        self.risk_repo = get_risk_repo()
        self.borehole_repo = get_borehole_repo()
        self.geophysics_repo = get_geophysics_repo()
        self.report_repo = get_report_repo()
        self.manifest_repo = get_manifest_repo()

    def get_risk(self, rid: str) -> Dict[str, Any]:
        r = self.risk_repo.risk_by_id(rid)
        if not r:
            raise NotFoundError(f"风险对象 {rid} 不存在")

        bh_map = self.borehole_repo.borehole_map()
        geo_map = self.geophysics_repo.line_map()
        bhs = [bh_map[bid] for bid in r.get("borehole_ids", []) if bid in bh_map]
        geo = geo_map.get(r.get("geophysics_line"))
        related_sections = self.report_repo.sections_for_risk(rid)

        assets = self.manifest_repo.get_assets()
        return {
            "risk": r,
            "boreholes": bhs,
            "geophysics": geo,
            "report_sections": related_sections,
            "evidence_cards": [
                {"source": "正射影像", "icon": "image",
                 "content": r["evidence"]["image"],
                 "file": assets["orthophoto"].get("image"), "kind": "image"},
                {"source": "三维点云", "icon": "mountain",
                 "content": r["evidence"]["pointcloud"],
                 "file": assets["pointcloud"].get("file"), "kind": "pointcloud"},
                {"source": "物探剖面", "icon": "wave",
                 "content": r["evidence"]["geophysics"],
                 "file": geo["image"] if geo else None, "kind": "geophysics",
                 "extra": geo},
                {"source": "钻孔资料", "icon": "drill",
                 "content": r["evidence"]["borehole"],
                 "file": [f"boreholes/{b['id']}.png" for b in bhs],
                 "kind": "borehole", "extra": bhs},
                {"source": "勘察报告", "icon": "doc",
                 "content": r["evidence"]["report"],
                 "file": None, "kind": "text", "extra": related_sections},
            ],
        }
