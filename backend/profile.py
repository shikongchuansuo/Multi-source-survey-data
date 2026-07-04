# -*- coding: utf-8 -*-
"""
沿线地质纵剖面分析
==================
从 DEM 采样沿隧道线路的地表高程，结合隧道设计纵断面（简化为线性），
生成工程上最重要的"地质纵剖面图"数据：
  - 地表高程线（地形）
  - 隧道设计高程线（纵断面）
  - 隧道埋深（地表 - 隧道高程）
  - 钻孔投影（把沿线钻孔的地层简化标到剖面位置）
  - 风险区段标注

这是隧道工程地质勘察最核心的一张图：把地形、地层、隧道、风险统一在里程轴上。
"""
import os
import json
import math
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")


def _load(*path):
    with open(os.path.join(DATA, *path), "r", encoding="utf-8") as f:
        return json.load(f)


MANIFEST = _load("manifest.json")
BOREHOLES = _load("boreholes", "boreholes.json")
RISKS = MANIFEST["risk_objects"]
ROUTE = MANIFEST["route"]

# DEM 参数（与 generate_data.py 一致）
CELL = 2.0
NCOLS = 500
NROWS = 400


def _load_dem_grid():
    """从 meta + dem 数据重建 Z 网格。
    这里不存原始 Z（太大），改用与 generate_data 相同的算法重建，保证一致。"""
    # 复刻 generate_data.build_dem 的算法
    x = np.linspace(0, 1000, NCOLS)
    y = np.linspace(0, 800, NROWS)
    X, Y = np.meshgrid(x, y)
    def route_y(x):
        return 400.0 + 30.0 * math.sin(2 * math.pi * x / 900.0)
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
                        - ((Y - route_y(985.0)) ** 2) / (2 * 18.0 ** 2))
    rng = np.random.default_rng(42)
    Z += rng.normal(0, 0.4, Z.shape)
    return X, Y, Z


_X, _Y, _Z = _load_dem_grid()


def _bilinear(xs, ys):
    """对 DEM 网格双线性插值。"""
    col = np.clip(xs / CELL, 0, NCOLS - 1.0001)
    row = np.clip(ys / CELL, 0, NROWS - 1.0001)
    c0 = np.floor(col).astype(int); c1 = c0 + 1
    r0 = np.floor(row).astype(int); r1 = r0 + 1
    fx = col - c0; fy = row - r0
    return (_Z[r0, c0] * (1 - fx) * (1 - fy) + _Z[r0, c1] * fx * (1 - fy)
            + _Z[r1, c0] * (1 - fx) * fy + _Z[r1, c1] * fx * fy)


def compute_route_profile():
    """计算沿线路的地质纵剖面。"""
    cl = ROUTE["centerline"]
    n = len(cl)
    # 里程（米）与对应 (X, Y)
    miles = np.array([p["mileage_m"] for p in cl])
    xs = np.array([p["xy"][0] for p in cl])
    ys = np.array([p["xy"][1] for p in cl])
    # 地表高程
    surf = _bilinear(xs, ys)
    # 隧道设计纵断面：进口(K12+000)高程 995，出口(K13+000)高程 1010，简化线性 + 微坡
    # 实际纵坡按 1.5% 上坡
    tun_start_h = float(surf[0]) - 12  # 洞口埋深约 12m
    tun_end_h = tun_start_h + 15  # 纵坡约 1.5%
    tunnel_h = np.linspace(tun_start_h, tun_end_h, n)

    # 钻孔投影：找每个钻孔最近的线路点
    bh_projections = []
    for bh in BOREHOLES:
        bx, by = bh["xy"]
        # 距离每个线路点的距离
        d = np.sqrt((xs - bx) ** 2 + (ys - by) ** 2)
        idx = int(np.argmin(d))
        bh_projections.append({
            "id": bh["id"], "mileage_m": int(miles[idx]),
            "mileage": bh["mileage"], "offset_m": round(float(d[idx]), 1),
            "elevation": bh["elevation"], "depth_m": bh["depth_m"],
            "water_depth_m": bh.get("water_depth_m"),
            "top_lithology": bh["layers"][0]["lithology"],
            "bedrock": bh["layers"][-1]["lithology"],
            "profile_x": int(miles[idx] - 12000),  # 相对 K12+000 的米数
        })

    # 风险区段
    risk_zones = []
    for r in sorted(RISKS, key=lambda x: x["mileage_m"]):
        risk_zones.append({
            "id": r["id"], "mileage": r["mileage"],
            "start_x": max(0, int(r["mileage_m"] - 12000 - 40)),
            "end_x": min(1000, int(r["mileage_m"] - 12000 + 40)),
            "level": r["risk_level"], "type_cn": r["type_cn"],
        })

    return {
        "mileage_x": [int(m - 12000) for m in miles],   # 0..1000
        "mileage_labels": ["K12+" + str(int(m - 12000)).zfill(3) for m in miles],
        "surface_elev": [round(float(s), 1) for s in surf],
        "tunnel_elev": [round(float(t), 1) for t in tunnel_h],
        "cover_depth": [round(float(s - t), 1) for s, t in zip(surf, tunnel_h)],
        "boreholes": bh_projections,
        "risk_zones": risk_zones,
        "stats": {
            "max_cover": round(float(max(surf - tunnel_h)), 1),
            "min_cover": round(float(min(surf - tunnel_h)), 1),
            "surface_range": [round(float(surf.min()), 1), round(float(surf.max()), 1)],
            "tunnel_grade_pct": 1.5,
        }
    }


if __name__ == "__main__":
    p = compute_route_profile()
    print("沿线剖面点数:", len(p["mileage_x"]))
    print("地表高程范围:", p["stats"]["surface_range"])
    print("隧道埋深范围:", p["stats"]["min_cover"], "-", p["stats"]["max_cover"], "m")
    print("钻孔投影:", len(p["boreholes"]), "个")
    for bh in p["boreholes"][:3]:
        print(f"  {bh['id']} -> 里程 K12+{bh['profile_x']:03d}, 偏距 {bh['offset_m']}m, 高程 {bh['elevation']}m")
    print("风险区段:", len(p["risk_zones"]))
    print("✓ 剖面计算完成")
