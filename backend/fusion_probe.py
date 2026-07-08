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

import ontology
import structures3d
import voxel_model

# ---- 体素模型缓存（探针高频调用，避免重复反演）----
_VOX_CACHE = None


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


def probe(x, y):
    """跨模态时空探针主入口。x,y 为工程坐标（米）。"""
    x = max(0.0, min(1000.0, float(x)))
    y = max(0.0, min(800.0, float(y)))
    surf = structures3d._elev_at(x, y)
    inside, nearest = _risks_at(x, y)
    _, vox_meta = _voxel()
    return {
        "x": round(x, 1), "y": round(y, 1),
        "mileage": _mileage_label(x),
        "terrain": {
            "surface_z": round(surf, 1),
            "slope_deg": round(_slope_deg(x, y), 1),
            "source": "DEM/三维点云（同源地形）",
        },
        "orthophoto": {
            # 归一化影像坐标（u 向东, v 向下），前端据此裁切影像块
            "u": round(x / 1000.0, 4),
            "v": round(1.0 - y / 800.0, 4),
        },
        "lithology_column": _lithology_column(x, y),
        "voxel_source": vox_meta.get("source"),
        "boreholes": _nearest_boreholes(x, y),
        "geophysics": _geophysics_at(x, y),
        "risk_inside": inside,
        "risk_nearest": nearest,
        "note": "统一工程坐标系为时空一致性基准；岩性语义来自领域本体",
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
