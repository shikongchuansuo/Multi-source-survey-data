# -*- coding: utf-8 -*-
"""
跨模态时空关联探针
==================
给定工程坐标 (x, y)，一次性检索该位置在**全部数据模态**中的对应信息：

  - 遥感/地形：里程、地表高程(DEM)、坡度、正射影像归一化坐标
  - 体素地质：该点位的岩性柱（本体语义标注）
  - 钻探：最近钻孔（距离排序）
  - 物探：穿过该点邻域的测线 + 对应桩号的电阻率-深度曲线
  - 风险：点在哪个风险区内（射线法）+ 最近风险区

这是「基于交叉模态相似性的时空融合」的可交互实现——统一工程坐标系
即时空一致性基准，任一位置可关联出所有模态的实例数据（实例数据关联组合）。
"""
import json
import math
import os

import numpy as np

import disposal_rules
import ontology
import structures3d
import voxel_model

# ---- 体素模型缓存（探针高频调用，避免重复反演）----
_VOX_CACHE = None

# 六维评分维度：与 analytics_service.DIMS 保持同名同序，
# 使探针点位与正式风险区在雷达图上视觉可比（各自独立求值，engines 间不互相 import）。
DIMS = [
    {"name": "地形坡度", "max": 100},
    {"name": "高差起伏", "max": 100},
    {"name": "物探异常", "max": 100},
    {"name": "钻孔揭露", "max": 100},
    {"name": "地下水", "max": 100},
    {"name": "综合等级", "max": 100},
]


def _voxel():
    """缓存的体素模型：(vox ndarray (nz,ny,nx), meta dict)。"""
    global _VOX_CACHE
    if _VOX_CACHE is None:
        m = voxel_model.build_voxel_model()
        nx, ny, nz = m["shape"]
        vox = np.asarray(m["data"], dtype=np.int32).reshape(nz, ny, nx)
        _VOX_CACHE = (vox, m)
    return _VOX_CACHE


def _mileage_label(x):
    """X 坐标(0..1000) → 里程标 K12+xxx。"""
    return "K12+%03d" % int(round(max(0, min(1000, x))))


def _slope_deg(x, y, h=5.0):
    """DEM 中心差分坡度（度）。"""
    e = structures3d._elev_at
    gx = (e(min(1000, x + h), y) - e(max(0, x - h), y)) / (2 * h)
    gy = (e(x, min(800, y + h)) - e(x, max(0, y - h))) / (2 * h)
    return math.degrees(math.atan(math.hypot(gx, gy)))


def _point_in_polygon(x, y, poly):
    """射线法点在多边形内判定。poly: [[x,y],...]"""
    inside = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]
        x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            xin = (x2 - x1) * (y - y1) / (y2 - y1) + x1
            if x < xin:
                inside = not inside
    return inside


def _lithology_column(x, y):
    """体素模型中 (x,y) 处的岩性柱（相邻同类合并，带本体语义）。"""
    vox, m = _voxel()
    nx, ny, nz = m["shape"]
    dx, dy, dz = m["spacing_m"]
    ox, oy, oz = m["origin_xyz"]
    ix = int((x - ox) / dx)
    iy = int((y - oy) / dy)
    if not (0 <= ix < nx and 0 <= iy < ny):
        return []
    col = vox[:, iy, ix]                     # 自下(iz=0)而上
    nodata = m["nodata"]
    segs = []
    # 自上而下扫描，合并相邻同类
    for iz in range(nz - 1, -1, -1):
        v = int(col[iz])
        if v == nodata:
            continue
        top_z = oz + (iz + 1) * dz
        bot_z = oz + iz * dz
        if segs and segs[-1]["code"] == v:
            segs[-1]["bottom_z"] = round(bot_z, 1)
        else:
            info = ontology.lithology_info(v) or {}
            segs.append({
                "code": v,
                "name_cn": info.get("name_cn", f"类别{v}"),
                "color": info.get("color", "#777777"),
                "surrounding_rock_class": info.get("surrounding_rock_class"),
                "engineering_property": info.get("engineering_property"),
                "top_z": round(top_z, 1),
                "bottom_z": round(bot_z, 1),
            })
    return segs


def _nearest_boreholes(x, y, k=3):
    """距离最近的 k 个钻孔。"""
    out = []
    for b in structures3d.BOREHOLES:
        bx, by = b["xy"]
        out.append({
            "id": b["id"], "mileage": b["mileage"],
            "distance_m": round(math.hypot(bx - x, by - y), 1),
            "depth_m": b["depth_m"],
            "n_layers": len(b["layers"]),
        })
    out.sort(key=lambda r: r["distance_m"])
    return out[:k]


# 物探测线关联的最大垂距（米）：超出则认为该模态在此位置无覆盖
_GEO_MAX_DIST = 80.0


def _geophysics_at(x, y):
    """该点邻域内的物探测线：投影桩号处的电阻率-深度曲线。"""
    lines_path = os.path.join(structures3d.DATA, "geophysics", "lines.json")
    if not os.path.exists(lines_path):
        return []
    with open(lines_path, "r", encoding="utf-8") as f:
        lines = json.load(f)
    import csv
    hits = []
    for ln in lines:
        sx, sy = ln["start_xy"]
        ex, ey = ln["end_xy"]
        length = math.hypot(ex - sx, ey - sy) or 1.0
        ux, uy = (ex - sx) / length, (ey - sy) / length
        t = (x - sx) * ux + (y - sy) * uy          # 投影桩号
        t = max(0.0, min(length, t))
        px, py = sx + ux * t, sy + uy * t          # 投影点
        dist = math.hypot(x - px, y - py)
        if dist > _GEO_MAX_DIST:
            continue
        csv_path = os.path.join(structures3d.DATA, *ln["csv"].split("/"))
        if not os.path.exists(csv_path):
            continue
        # 找最近桩号的电阻率剖面
        by_sta = {}
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                s = float(row["station_m"])
                by_sta.setdefault(s, []).append(
                    (float(row["depth_m"]), float(row["rho_ohm_m"])))
        if not by_sta:
            continue
        s_near = min(by_sta, key=lambda s: abs(s - t))
        prof = sorted(by_sta[s_near])
        hits.append({
            "id": ln["id"], "name": ln["name"], "method": ln["method"],
            "related_risk": ln.get("related_risk"),
            "distance_m": round(dist, 1),
            "station_m": round(s_near, 1),
            "depths": [round(d, 1) for d, _ in prof],
            "rho": [round(r, 1) for _, r in prof],
            "rho_min": round(min(r for _, r in prof), 1),
        })
    hits.sort(key=lambda h: h["distance_m"])
    return hits


def _risks_at(x, y):
    """点所在的风险区 + 最近风险区。"""
    inside, nearest = [], None
    for r in structures3d.RISKS:
        cx, cy = r["center_xy"]
        d = math.hypot(cx - x, cy - y)
        rec = {"id": r["id"], "mileage": r["mileage"],
               "type_cn": r["type_cn"], "risk_level": r["risk_level"],
               "distance_m": round(d, 1)}
        if _point_in_polygon(x, y, r["polygon_xy"]):
            inside.append(rec)
        if nearest is None or d < nearest["distance_m"]:
            nearest = rec
    return inside, nearest


def _relief_m(x, y, radius=40.0, n=5):
    """点位邻域地形起伏（NxN 网格采样窗口内最大-最小高程）。"""
    e = structures3d._elev_at
    zs = []
    for i in range(n):
        for j in range(n):
            dx = (i / (n - 1) - 0.5) * 2 * radius
            dy = (j / (n - 1) - 0.5) * 2 * radius
            zs.append(e(min(1000.0, max(0.0, x + dx)), min(800.0, max(0.0, y + dy))))
    return max(zs) - min(zs)


def _layer_thickness(lith, codes):
    """岩性柱中指定 code 集合的累计厚度（米）。"""
    return sum(s["top_z"] - s["bottom_z"] for s in lith if s["code"] in codes)


def _weathered_depth(lith):
    """风化层(全/强风化, 本体 weathering_grade in W3/W4)累计厚度。"""
    codes = {c["code"] for c in ontology.lithology_concepts()
              if c.get("weathering_grade") in ("W3", "W4")}
    return _layer_thickness(lith, codes)


def _score_point(slope_deg, relief_m, rho_min, weathered_m, has_fracture):
    """六维评分：与 analytics_service._score_risk 同一套公式，
    用探针实测的真实证据(坡度/起伏/电阻率/风化厚度)代入，使探针点位
    获得与正式风险区同等量纲、可直接比较的量化画像。
    """
    slope_score = min(100, round(slope_deg / 45 * 100))
    relief_score = min(100, round(relief_m / 60 * 100))
    rho = rho_min if rho_min is not None else 1000
    geo_score = max(0, min(100, round((1000 - rho) / 900 * 100)))
    bh_score = min(100, round(weathered_m / 15 * 70 + (100 - 80) / 100 * 30))
    water_score = 70 if has_fracture else 40
    avg = (slope_score + relief_score + geo_score + bh_score + water_score) / 5
    level = "高" if avg >= 65 else ("中高" if avg >= 45 else "中")
    level_score = {"高": 90, "中高": 70, "中": 50}[level]
    scores = {"slope": slope_score, "relief": relief_score, "geophysics": geo_score,
              "borehole": bh_score, "groundwater": water_score, "level": level_score}
    return scores, level


def _dominant_type(scores):
    """按三种风险机制(边坡/富水破碎/松散堆积)对应评分取最高者，
    推断该点位的主导风险类型 —— 用于复用 disposal_rules 的处置建议文本。
    """
    cand = {"slope_instability": scores["slope"],
            "water_rich_fracture": scores["geophysics"],
            "loose_deposit": scores["borehole"]}
    return max(cand, key=cand.get)


def _interpret_text(mileage, slope_deg, relief_m, lith, geo, boreholes,
                     risk_inside, risk_nearest, weathered_m):
    """基于该点真实证据拼接的自然语言解读（风格对齐正式风险区的 interpretation 字段）。"""
    parts = [f"{mileage} 位置地表坡度 {slope_deg:.1f}°，邻域地形起伏约 {relief_m:.0f}m。"]
    if lith:
        top = lith[0]
        parts.append(
            f"体素岩性柱（钻孔+物探反演）显示表层为{top['name_cn']}"
            f"（围岩{top.get('surrounding_rock_class') or '—'}），风化层累计厚度约 {weathered_m:.0f}m。")
    if geo:
        g0 = geo[0]
        anomaly = "，存在低阻异常，指示富水或破碎发育" if g0["rho_min"] < 200 else "，未见明显低阻异常"
        parts.append(f"最近物探测线 {g0['id']}（垂距{g0['distance_m']}m）实测最低电阻率 {g0['rho_min']}Ω·m{anomaly}。")
    if boreholes:
        b0 = boreholes[0]
        parts.append(f"最近钻孔 {b0['id']} 距此 {b0['distance_m']}m（孔深{b0['depth_m']}m），可作为该点地层验证依据。")
    if risk_inside:
        parts.append(f"该点落入已圈定风险区：{'、'.join(r['type_cn'] for r in risk_inside)}。")
    elif risk_nearest:
        parts.append(f"该点未落入已圈定风险区，距最近风险区（{risk_nearest['type_cn']}）约 {risk_nearest['distance_m']}m。")
    return "".join(parts)


def probe(x, y):
    """跨模态时空探针主入口。x,y 为工程坐标（米）。

    与正式风险区(selectRisk)对等的全链路联动入口：不仅检索各模态实例数据，
    还基于真实证据现算六维评分(与风险雷达图同一套公式)、推断主导风险机制、
    生成文字解读 + 处置建议(复用 disposal_rules，与报告生成同源)，
    供前端一次性驱动 3D 定位/里程轴/雷达图/风险解释面板等全部联动视图。
    """
    x = max(0.0, min(1000.0, float(x)))
    y = max(0.0, min(800.0, float(y)))
    surf = structures3d._elev_at(x, y)
    slope_deg = _slope_deg(x, y)
    relief_m = _relief_m(x, y)
    inside, nearest = _risks_at(x, y)
    lith = _lithology_column(x, y)
    geo = _geophysics_at(x, y)
    boreholes = _nearest_boreholes(x, y)
    _, vox_meta = _voxel()

    weathered_m = _weathered_depth(lith)
    fracture_m = _layer_thickness(lith, {5})
    deposit_m = _layer_thickness(lith, {0})
    rho_min = geo[0]["rho_min"] if geo else None
    scores, level = _score_point(slope_deg, relief_m, rho_min, weathered_m, fracture_m > 0)
    dom_type = _dominant_type(scores)
    dom_info = ontology.risk_type_info(dom_type) or {}
    params = {"max_slope_deg": round(slope_deg, 1), "relief_m": round(relief_m, 1),
              "weathered_depth_m": round(weathered_m, 1), "fracture_width_m": round(fracture_m, 1),
              "deposit_depth_m": round(deposit_m, 1)}
    mileage = _mileage_label(x)

    return {
        "x": round(x, 1), "y": round(y, 1),
        "mileage": mileage,
        "terrain": {
            "surface_z": round(surf, 1),
            "slope_deg": round(slope_deg, 1),
            "relief_m": round(relief_m, 1),
            "source": "DEM/三维点云（同源地形）",
        },
        "orthophoto": {
            # 归一化影像坐标（u 向东, v 向下），前端据此裁切影像块
            "u": round(x / 1000.0, 4),
            "v": round(1.0 - y / 800.0, 4),
        },
        "lithology_column": lith,
        "voxel_source": vox_meta.get("source"),
        "boreholes": boreholes,
        "geophysics": geo,
        "risk_inside": inside,
        "risk_nearest": nearest,
        # ---- 全链路联动新增字段 ----
        "scores": {"dims": DIMS,
                   "values": [scores["slope"], scores["relief"], scores["geophysics"],
                              scores["borehole"], scores["groundwater"], scores["level"]]},
        "level": level,
        "dominant_type": dom_type,
        "dominant_type_cn": dom_info.get("name_cn", dom_type),
        "interpretation": _interpret_text(mileage, slope_deg, relief_m, lith, geo, boreholes,
                                           inside, nearest, weathered_m),
        "design_suggestion": disposal_rules.bullets_for(dom_type, level, params),
        "note": "统一工程坐标系为时空一致性基准；岩性语义来自领域本体；评分/建议与正式风险区同一套算法",
    }


if __name__ == "__main__":
    d = probe(720, 430)   # R002 富水破碎带附近
    print("里程:", d["mileage"], " 高程:", d["terrain"]["surface_z"],
          " 坡度:", d["terrain"]["slope_deg"])
    print("岩性柱:", [(s["name_cn"], s["top_z"], s["bottom_z"])
                     for s in d["lithology_column"]])
    print("最近钻孔:", [(b["id"], b["distance_m"]) for b in d["boreholes"]])
    print("物探覆盖:", [(g["id"], g["distance_m"], g["rho_min"])
                       for g in d["geophysics"]])
    print("所在风险区:", d["risk_inside"], " 最近:", d["risk_nearest"]["id"])
