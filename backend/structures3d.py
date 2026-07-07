# -*- coding: utf-8 -*-
"""
三维地质结构数据
================
为前端 Three.js 场景提供"地质结构"几何数据，与点云同坐标系：
  - 隧道设计轴线（中心线 + 半径，前端用 TubeGeometry 渲染）
  - 钻孔三维信息（孔口坐标 X,Y,Z + 分层 + 水位，前端用分层圆柱渲染）
  - 异常体（风险区的地下低阻/破碎区，前端用半透明椭球渲染）

所有坐标与点云一致：原始工程坐标 (X 米, Y 米)，高程 Z 米。
前端约定：渲染时 X-=500, Y-=400, Z-=950，与点云对齐。
"""
import os
import csv
import json
import math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def _load(*p):
    with open(os.path.join(DATA, *p), "r", encoding="utf-8") as f:
        return json.load(f)


MANIFEST = _load("manifest.json")
BOREHOLES = _load("boreholes", "boreholes.json")
RISKS = MANIFEST["risk_objects"]
ROUTE = MANIFEST["route"]
CELL = 2.0
NCOLS = 500
NROWS = 400


def _route_y(x):
    return 400.0 + 30.0 * math.sin(2 * math.pi * x / 900.0)


def _build_dem():
    """重建 DEM 网格（与 generate_data/profile.py 一致）。"""
    x = np.linspace(0, 1000, NCOLS)
    y = np.linspace(0, 800, NROWS)
    X, Y = np.meshgrid(x, y)
    Z = 920.0 + 0.18 * (800 - Y) + 0.05 * X
    Z += 60.0 * np.exp(-((Y - 600.0) ** 2) / (2 * 70.0 ** 2))
    Z += 40.0 * np.exp(-((Y - 120.0) ** 2) / (2 * 60.0 ** 2))
    Z += -22.0 * np.exp(-((X - 200.0) ** 2) / (2 * 45.0 ** 2)
                         - ((Y - 470.0) ** 2) / (2 * 120.0 ** 2))
    Z += -16.0 * np.exp(-((X - 700.0) ** 2) / (2 * 55.0 ** 2)
                         - ((Y - 380.0) ** 2) / (2 * 90.0 ** 2))
    cx, cy = 430.0, 560.0
    d2 = (X - cx) ** 2 + (Y - cy) ** 2
    Z += -25.0 * np.exp(-d2 / (2 * 90.0 ** 2))
    Z += 12.0 * np.exp(-(((X - cx) - 70.0) ** 2) / (2 * 35.0 ** 2)
                        - ((Y - cy) ** 2) / (2 * 70.0 ** 2))
    Z += 12.0 * np.exp(-(((X - cx) + 70.0) ** 2) / (2 * 35.0 ** 2)
                        - ((Y - cy) ** 2) / (2 * 70.0 ** 2))
    Z += -8.0 * np.exp(-((X - 985.0) ** 2) / (2 * 25.0 ** 2)
                        - ((Y - _route_y(985.0)) ** 2) / (2 * 18.0 ** 2))
    rng = np.random.default_rng(42)
    Z += rng.normal(0, 0.4, Z.shape)
    return Z


_Z = _build_dem()


def _elev_at(x, y):
    """双线性插值高程。"""
    col = max(0, min(NCOLS - 1.001, x / CELL))
    row = max(0, min(NROWS - 1.001, y / CELL))
    c0 = int(col); r0 = int(row)
    fx, fy = col - c0, row - r0
    return float(_Z[r0, c0] * (1 - fx) * (1 - fy) + _Z[r0, c0 + 1] * fx * (1 - fy)
                 + _Z[r0 + 1, c0] * (1 - fx) * fy + _Z[r0 + 1, c0 + 1] * fx * fy)


def build_3d_structures():
    """构建三维地质结构数据。"""
    # 1. 隧道轴线（加密采样点）
    cl = ROUTE["centerline"]
    # 在相邻中心线点之间插值加密，得到平滑曲线
    axis_pts = []
    for i in range(len(cl) - 1):
        a, b = cl[i], cl[i + 1]
        for t in np.linspace(0, 1, 10, endpoint=False):
            x = a["xy"][0] + (b["xy"][0] - a["xy"][0]) * t
            y = a["xy"][1] + (b["xy"][1] - a["xy"][1]) * t
            # 隧道设计高程：地表 - 埋深。埋深按里程从 12m 增到 ~50m 再到洞口
            mile = a["mileage_m"] + (b["mileage_m"] - a["mileage_m"]) * t
            rel = (mile - 12000) / 1000  # 0..1
            depth = 12 + rel * 38  # 12m -> 50m
            surf = _elev_at(x, y)
            axis_pts.append([round(x, 1), round(y, 1), round(surf - depth, 1)])
    # 末点
    last = cl[-1]
    axis_pts.append([last["xy"][0], last["xy"][1],
                     round(_elev_at(last["xy"][0], last["xy"][1]) - 8, 1)])

    tunnel = {
        "axis": axis_pts,            # [[x,y,z], ...] 工程坐标
        "radius": 7.0,               # 隧道开挖半径(米)
        "label": "隧道设计轴线 (双线铁路)",
    }

    # 2. 钻孔三维
    boreholes_3d = []
    for b in BOREHOLES:
        bx, by = b["xy"]
        surf_z = _elev_at(bx, by)  # 用 DEM 高程（比钻孔 elevation 更一致）
        # 分层：把每层转成 [top_z, bottom_z, lithology, color]
        layers_3d = []
        for L in b["layers"]:
            layers_3d.append({
                "top_z": round(surf_z - L["top"], 1),
                "bottom_z": round(surf_z - L["bottom"], 1),
                "lithology": L["lithology"],
                "color": L["color"],
            })
        boreholes_3d.append({
            "id": b["id"], "x": bx, "y": by,
            "surface_z": round(surf_z, 1),
            "depth_m": b["depth_m"],
            "water_z": round(surf_z - b["water_depth_m"], 1) if b.get("water_depth_m") is not None else None,
            "layers": layers_3d,
        })

    # 3. 异常体（风险区的地下不良地质体）
    anomalies = []
    for r in RISKS:
        cx, cy = r["center_xy"]
        p = r["evidence"].get("params", {})
        # 异常中心深度（地下）
        if r["type"] == "water_rich_fracture":
            depth = p.get("fracture_width_m", 20)  # 富水破碎带
            size = [120, 90, depth]
            color = "rgba(40,120,220,.35)"   # 蓝色（含水）
        elif r["type"] == "slope_instability":
            depth = p.get("weathered_depth_m", 8)
            size = [140, 100, depth]
            color = "rgba(220,80,60,.35)"    # 红色（松动）
        else:
            depth = p.get("deposit_depth_m", 7)
            size = [100, 70, depth]
            color = "rgba(220,180,80,.30)"   # 黄色（松散）
        surf_z = _elev_at(cx, cy)
        anomalies.append({
            "risk_id": r["id"], "x": cx, "y": cy,
            "center_z": round(surf_z - depth * 0.5, 1),
            "size": size,                 # [半轴X, 半轴Y, 半轴Z] 米
            "color": color,
            "label": f"{r['mileage']} {r['type_cn']}",
            "type": r["type"],
        })

    return {
        "tunnel": tunnel,
        "boreholes": boreholes_3d,
        "anomalies": anomalies,
        "coord_offset": {"x": 500, "y": 400, "z": 950},  # 前端渲染时减去
        "note": "坐标为工程局部系；前端渲染时 X-=500, Y-=400, Z-=950 与点云对齐",
    }


def build_3d_sections():
    """物探测线三维帷幕面数据。

    把每条测线的电阻率断面 (station × depth) 展成随地形起伏的
    三维"帷幕"网格：每个桩号给出平面坐标 xy 与地表高程 surface_z，
    前端按 z = surface_z - depth 生成竖直曲面顶点，用电阻率着色。
    """
    lines = _load("geophysics", "lines.json")
    out = []
    for ln in lines:
        path = os.path.join(DATA, *ln["csv"].split("/"))
        stations, depths, grid = set(), set(), {}
        with open(path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                s = float(row["station_m"])
                d = float(row["depth_m"])
                grid[(s, d)] = float(row["rho_ohm_m"])
                stations.add(s)
                depths.add(d)
        stations = sorted(stations)
        depths = sorted(depths)
        sx, sy = ln["start_xy"]
        ex, ey = ln["end_xy"]
        length = math.hypot(ex - sx, ey - sy) or 1.0
        ux, uy = (ex - sx) / length, (ey - sy) / length
        xy, surf = [], []
        for s in stations:
            x, y = sx + ux * s, sy + uy * s
            xy.append([round(x, 1), round(y, 1)])
            surf.append(round(_elev_at(x, y), 1))
        # rho[depth_idx][station_idx]
        rho = [[round(grid.get((s, d), 0.0), 1) for s in stations]
               for d in depths]
        vals = [v for r_ in rho for v in r_]
        out.append({
            "id": ln["id"], "name": ln["name"], "method": ln["method"],
            "related_risk": ln.get("related_risk"),
            "stations": [round(s, 1) for s in stations],
            "depths": [round(d, 1) for d in depths],
            "xy": xy,
            "surface_z": surf,
            "rho": rho,
            "rho_min": round(min(vals), 1),
            "rho_max": round(max(vals), 1),
        })
    return {
        "lines": out,
        "coord_offset": {"x": 500, "y": 400, "z": 950},
        "note": "帷幕面顶点 z = surface_z[i] - depths[j]；渲染时减 coord_offset",
    }


if __name__ == "__main__":
    d = build_3d_structures()
    print("隧道轴线点数:", len(d["tunnel"]["axis"]))
    print("  起点高程:", d["tunnel"]["axis"][0][2], "终点高程:", d["tunnel"]["axis"][-1][2])
    print("钻孔三维:", len(d["boreholes"]))
    for b in d["boreholes"][:2]:
        print(f"  {b['id']}: 孔口高程 {b['surface_z']}, {len(b['layers'])} 层")
    print("异常体:", len(d["anomalies"]))
    for a in d["anomalies"]:
        print(f"  {a['risk_id']}: 中心高程 {a['center_z']}, 尺寸 {a['size']}")
    print("✓ 三维结构构建完成")
