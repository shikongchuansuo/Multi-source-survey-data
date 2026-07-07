# -*- coding: utf-8 -*-
"""文件源 repository 实现（``use_db=False`` 模式）。

返回结构与重构前 ``backend/app.py`` 的模块级全局（``MANIFEST`` /
``RISK_BY_ID`` / ``BOREHOLES`` / ``GEO_LINES`` / ``REPORT``）逐字段一致。
这是 API 兼容性红线的直接保证。
"""
from __future__ import annotations

from functools import lru_cache
from typing import Any, Dict, List

from app.repositories.base import BaseRepo


class ManifestFileRepo(BaseRepo):
    """项目元信息、线路、数据源清单、风险对象摘要。"""

    @lru_cache(maxsize=1)
    def _manifest(self) -> Dict[str, Any]:
        return self._read_json("manifest.json")

    def get_manifest(self) -> Dict[str, Any]:
        return self._manifest()

    def get_project(self) -> Dict[str, Any]:
        return self._manifest()["project"]

    def get_route(self) -> Dict[str, Any]:
        return self._manifest()["route"]

    def get_data_sources(self) -> List[Dict[str, Any]]:
        return self._manifest().get("data_sources", [])

    def get_assets(self) -> Dict[str, Any]:
        """DEM / 正射 / 点云 资产路径。"""
        m = self._manifest()
        return {
            "dem": m.get("dem", {}),
            "orthophoto": m.get("orthophoto", {}),
            "pointcloud": m.get("pointcloud", {}),
        }


class RiskFileRepo(BaseRepo):
    """风险对象。"""

    @lru_cache(maxsize=1)
    def _risks(self) -> List[Dict[str, Any]]:
        return self._read_json("manifest.json")["risk_objects"]

    def all_risks(self) -> List[Dict[str, Any]]:
        return self._risks()

    def risk_by_id(self, rid: str) -> Dict[str, Any] | None:
        for r in self._risks():
            if r["id"] == rid:
                return r
        return None

    def risk_ids(self) -> List[str]:
        return [r["id"] for r in self._risks()]

    def risk_map(self) -> Dict[str, Dict[str, Any]]:
        return {r["id"]: r for r in self._risks()}


class BoreholeFileRepo(BaseRepo):
    """钻孔。"""

    @lru_cache(maxsize=1)
    def _boreholes(self) -> List[Dict[str, Any]]:
        return self._read_json("boreholes", "boreholes.json")

    def all_boreholes(self) -> List[Dict[str, Any]]:
        return self._boreholes()

    def borehole_map(self) -> Dict[str, Dict[str, Any]]:
        return {b["id"]: b for b in self._boreholes()}

    def borehole_by_id(self, bid: str) -> Dict[str, Any] | None:
        return self.borehole_map().get(bid)


class GeophysicsFileRepo(BaseRepo):
    """物探测线 + 电阻率网格。"""

    @lru_cache(maxsize=1)
    def _lines(self) -> List[Dict[str, Any]]:
        return self._read_json("geophysics", "lines.json")

    def all_lines(self) -> List[Dict[str, Any]]:
        return self._lines()

    def line_map(self) -> Dict[str, Dict[str, Any]]:
        return {g["id"]: g for g in self._lines()}

    def line_by_id(self, lid: str) -> Dict[str, Any] | None:
        return self.line_map().get(lid)

    def read_grid_rows(self, csv_rel: str) -> List[tuple]:
        """读取物探 CSV：返回 [(station_m, depth_m, rho_ohm_m), ...]。"""
        rows = []
        for row in self.store.read_csv_rows(csv_rel):
            rows.append((
                float(row["station_m"]),
                float(row["depth_m"]),
                float(row["rho_ohm_m"]),
            ))
        return rows


class ReportFileRepo(BaseRepo):
    """勘察报告段落。"""

    @lru_cache(maxsize=1)
    def _report(self) -> Dict[str, Any]:
        return self._read_json("report", "survey_report.json")

    def get_report(self) -> Dict[str, Any]:
        return self._report()

    def sections(self) -> List[Dict[str, Any]]:
        return self._report().get("sections", [])

    def sections_for_risk(self, rid: str) -> List[Dict[str, Any]]:
        return [s for s in self.sections() if rid in s.get("related_risks", [])]
