# -*- coding: utf-8 -*-
"""物探业务。

对应原 ``app.py::get_geophysics`` 与 ``get_geophysics_grid``。
后者把 CSV 三列 (station_m, depth_m, rho_ohm_m) 重整为 ECharts 热力图
所需的 [x_idx, y_idx, value] 网格。
"""
from __future__ import annotations

from typing import Any, Dict

from app.core.exceptions import NotFoundError
from app.repositories import get_geophysics_repo


class GeophysicsService:
    def __init__(self) -> None:
        self.repo = get_geophysics_repo()

    def list_or_get(self, lid: str | None = None) -> Dict[str, Any]:
        if lid:
            g = self.repo.line_by_id(lid)
            if not g:
                raise NotFoundError(f"物探测线 {lid} 不存在")
            return g
        return {"lines": self.repo.all_lines()}

    def get_grid(self, lid: str) -> Dict[str, Any]:
        g = self.repo.line_by_id(lid)
        if not g:
            raise NotFoundError(f"物探测线 {lid} 不存在")
        if not self.repo.store.exists(g["csv"]):
            raise NotFoundError("物探 CSV 数据不存在")

        rows = self.repo.read_grid_rows(g["csv"])
        # 去重轴
        stations = sorted(set(r[0] for r in rows))
        depths = sorted(set(r[1] for r in rows))
        sta_idx = {s: i for i, s in enumerate(stations)}
        dep_idx = {d: i for i, d in enumerate(depths)}
        data = []
        rho_vals = []
        for s, d, rho in rows:
            data.append([sta_idx[s], dep_idx[d], round(rho, 1)])
            rho_vals.append(rho)
        rho_min = round(min(rho_vals), 1)
        rho_max = round(max(rho_vals), 1)
        return {
            "line": g,
            "stations": [round(s, 1) for s in stations],
            "depths": [round(d, 1) for d in depths],
            "data": data,
            "rho_min": rho_min,
            "rho_max": rho_max,
            "anomaly": {"x": g["length_m"] / 2,
                        "depth": g["anomaly_depth_m"],
                        "rho": g["rho_min"]},
        }
