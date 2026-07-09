# -*- coding: utf-8 -*-
"""分析业务：多维评分 + 三维地形 + 沿线剖面。

对应原 ``app.py`` 的 ``_score_risk``、``risk_scores``、
``get_3d_structures``、``get_3d_terrain``、``get_route_profile``。

评分算法（``_score_risk``）原样迁移，保证雷达图数值不变。
3D / 剖面调用 ``engines`` 模块（惰性加载）。
"""
from __future__ import annotations

import threading
from typing import Any, Callable, Dict, List, Tuple

from app.core.exceptions import NotFoundError
from app.engines import (profile_engine, structures3d_engine, voxel_engine,
                         fusion_engine, ontology_engine, landcover_engine)
from app.repositories import get_risk_repo, get_manifest_repo

# 六个评分维度（与原 app.py 完全一致）
DIMS = [
    {"name": "地形坡度", "max": 100},
    {"name": "高差起伏", "max": 100},
    {"name": "物探异常", "max": 100},
    {"name": "钻孔揭露", "max": 100},
    {"name": "地下水", "max": 100},
    {"name": "综合等级", "max": 100},
]


def _score_risk(r: Dict[str, Any]) -> Dict[str, int]:
    """根据风险参数 + 证据，计算各维度评分 (0-100)。

    原样迁移自 ``app.py::_score_risk``，不改算法。
    """
    p = r["evidence"].get("params", {})
    slope = p.get("max_slope_deg", p.get("avg_slope_deg", 15))
    slope_score = min(100, round(slope / 45 * 100))
    relief = p.get("relief_m", 10)
    relief_score = min(100, round(relief / 60 * 100))
    rho = p.get("rho_min", 1000)
    geo_score = max(0, min(100, round((1000 - rho) / 900 * 100)))
    weathered = p.get("weathered_depth_m", p.get("deposit_depth_m", 5))
    rqd = p.get("rqd_pct", 80)
    bh_score = min(100, round(weathered / 15 * 70 + (100 - rqd) / 100 * 30))
    wd = p.get("water_depth_m")
    water_score = (max(20, min(100, round((10 - wd) / 10 * 100)))
                   if wd is not None else 40)
    level_score = {"高": 90, "中高": 70, "中": 50}.get(r["risk_level"], 50)
    return {
        "slope": slope_score, "relief": relief_score,
        "geophysics": geo_score, "borehole": bh_score,
        "groundwater": water_score, "level": level_score,
    }


class AnalyticsService:
    def __init__(self) -> None:
        self.risk_repo = get_risk_repo()
        self.manifest_repo = get_manifest_repo()
        # 进程内结果缓存：底层计算引擎(体素反演/地物聚类/3D 结构/沿线剖面)
        # 都是数据驱动且不可变，重复请求无需重算。fusion_probe 已用同样范式
        # 的 _VOX_CACHE，此处把 memo 下沉到 service 层统一管理多端点。
        self._cache: Dict[str, Any] = {}
        self._lock = threading.Lock()
        self._stats: Dict[str, int] = {"miss": 0, "hit": 0}

    def _cached(self, key: str, builder: Callable[[], Any]) -> Any:
        """线程安全的结果缓存。首次计算后永久命中，返回同一对象引用。

        底层数据(钻孔/物探/DEM)在运行期不变；若数据更新，重启进程即可。
        FastAPI 序列化时会拷贝一份，返回共享只读 dict 是安全的。
        """
        v = self._cache.get(key)
        if v is not None:
            self._stats["hit"] += 1
            return v
        with self._lock:
            v = self._cache.get(key)
            if v is not None:           # 双检：等锁期间可能已被其它线程算好
                self._stats["hit"] += 1
                return v
            v = builder()
            self._cache[key] = v
            self._stats["miss"] += 1
            return v

    # ---- 风险多维评分 ----
    def risk_scores(self, rid: str | None = None) -> Dict[str, Any]:
        if rid:
            r = self.risk_repo.risk_by_id(rid)
            if not r:
                raise NotFoundError(f"风险 {rid} 不存在")
            s = _score_risk(r)
            return {"dimensions": DIMS, "risk": {
                "id": rid, "name": r["name"], "mileage": r["mileage"],
                "level": r["risk_level"],
                "values": [s["slope"], s["relief"], s["geophysics"],
                           s["borehole"], s["groundwater"], s["level"]],
                "scores": s,
            }}
        series: List[Dict[str, Any]] = []
        for r in sorted(self.risk_repo.all_risks(), key=lambda x: x["mileage_m"]):
            s = _score_risk(r)
            series.append({
                "id": r["id"], "name": r["mileage"] + " " + r["type_cn"],
                "level": r["risk_level"],
                "values": [s["slope"], s["relief"], s["geophysics"],
                           s["borehole"], s["groundwater"], s["level"]],
            })
        return {"dimensions": DIMS, "risks": series}

    # ---- 风险评分特征贡献分解（瀑布图数据）----
    def risk_contribution(self, rid: str) -> Dict[str, Any]:
        """把风险总分分解到各维度，输出特征贡献瀑布图所需结构化数据。

        每个维度给出：得分、相对基准线(50分)的贡献、原始参数依据文字。
        这是"模型可解释性"的数据接口，前端画成瀑布图，NLU 的评分解释共用同一逻辑。
        """
        r = self.risk_repo.risk_by_id(rid)
        if not r:
            raise NotFoundError(f"风险 {rid} 不存在")
        s = _score_risk(r)
        p = r["evidence"].get("params", {})
        # 每个维度的原始依据文字（与 nlu._explain_score 保持一致）
        basis = {
            "slope": f"最大坡度 {p.get('max_slope_deg', p.get('avg_slope_deg', '—'))}°",
            "relief": f"高差起伏 {p.get('relief_m', '—')}m",
            "geophysics": f"最低电阻率 {p.get('rho_min', '—')}Ω·m",
            "borehole": (f"风化/堆积深度 {p.get('weathered_depth_m', p.get('deposit_depth_m', '—'))}m"
                         + (f"，RQD={rqd}%" if (rqd := p.get('rqd_pct')) else "")),
            "groundwater": (f"地下水位埋深 {p['water_depth_m']}m"
                            if p.get("water_depth_m") is not None else "未测到地下水"),
            "level": f"定性等级 {r['risk_level']}",
        }
        BASELINE = 50   # 基准线：50分（中等）
        # 维度顺序：DIMS 是 [{"name","max"},...]，key 来自 _score_risk 的字段名
        _DIM_KEYS = ["slope", "relief", "geophysics", "borehole", "groundwater", "level"]
        items = []
        for dim, key in zip(DIMS, _DIM_KEYS):
            score = s[key]
            items.append({
                "key": key, "name": dim["name"],
                "score": score,
                "contribution": score - BASELINE,   # 正=推高风险，负=拉低
                "basis": basis.get(key, ""),
            })
        total = round(sum(s.values()) / len(s))
        items.sort(key=lambda x: -x["contribution"])   # 贡献从高到低
        return {
            "risk_id": rid,
            "risk_name": r["name"],
            "mileage": r["mileage"],
            "level": r["risk_level"],
            "baseline": BASELINE,
            "total_score": total,
            "contributions": items,
            "note": "贡献 = 维度得分 - 基准线(50)；正值推高风险，负值拉低。"
                    "基准线 50 代表中等风险水平。",
        }

    # ---- 三维地质结构 ----
    def get_3d_structures(self) -> Dict[str, Any]:
        return self._cached("3d_structures", structures3d_engine.build_3d_structures)

    # ---- 物探剖面三维帷幕面 ----
    def get_3d_sections(self) -> Dict[str, Any]:
        return self._cached("3d_sections", structures3d_engine.build_3d_sections)

    # ---- 体素地质模型 ----
    # 体素反演(scipy RBF 空间插值 + 物探软约束)是加载期最重的计算，
    # 冷启动约 0.5~1.8s。结果由实测钻孔/物探驱动、运行期不变，适合长缓存。
    def get_3d_voxel(self) -> Dict[str, Any]:
        return self._cached("3d_voxel", voxel_engine.build_voxel_model)

    # ---- 跨模态时空探针 ----
    def fusion_probe(self, x: float, y: float) -> Dict[str, Any]:
        return fusion_engine.probe(x, y)

    # ---- 领域本体 + 实例映射 ----
    def get_ontology(self) -> Dict[str, Any]:
        return self._cached("ontology", ontology_engine.build_instance_mapping)

    # ---- 地物分类 ----
    def get_landcover(self) -> Dict[str, Any]:
        return self._cached("landcover", landcover_engine.build_landcover)

    # ---- 沿线剖面 ----
    def get_route_profile(self) -> Dict[str, Any]:
        return self._cached("route_profile", profile_engine.compute_route_profile)

    # ---- DEM 地形网格（降采样）----
    def get_3d_terrain(self, step: int = 4) -> Dict[str, Any]:
        # 结果随 step 变化，缓存键带上 step（前端只用 step=5，键碰撞几近为零）
        s = max(2, int(step))

        def _build() -> Dict[str, Any]:
            import numpy as np  # 局部导入，避免无 numpy 环境下 import 副作用
            Z = structures3d_engine._Z  # shape (NROWS=400, NCOLS=500)
            CELL = structures3d_engine.CELL
            NROWS, NCOLS = Z.shape
            sub = Z[::s, ::s]
            out_rows, out_cols = sub.shape
            elev = [[round(float(sub[r, c]), 1) for c in range(out_cols)]
                    for r in range(out_rows)]
            assets = self.manifest_repo.get_assets()
            return {
                "step": s,
                "ncols": out_cols,
                "nrows": out_rows,
                "elevations": elev,
                "cell": s * CELL,
                "extent": {"xmin": 0, "ymin": 0, "xmax": 1000, "ymax": 800},
                "texture": assets["orthophoto"].get("image"),
                "coord_offset": {"x": 500, "y": 400, "z": 950},
                "note": "elevations[row][col]，row 对应 Y(0=南,nrows-1=北)，"
                        "col 对应 X(0=东0,ncols-1=东1000)",
            }

        return self._cached(f"3d_terrain:{s}", _build)
