# -*- coding: utf-8 -*-
"""
数据生成器 —— 多源勘察数据联动展示与证据链追溯系统
==================================================
为"某铁路隧道洞口段"生成一套内部自洽的样例数据：
  - DEM（数字高程模型，GeoTIFF + PNG）
  - 正射影像（PNG，模拟真彩色）
  - 三维点云（PLY，与 DEM 同源，含坡度着色）
  - 线路轴线 / 里程数据
  - 物探剖面（高密度电法，含低阻异常）
  - 钻孔柱状图（数据 + 渲染图）
  - 勘察报告（文本 + 结构化证据）
  - 风险证据链表（核心：把多源证据挂在同一工程对象上）

所有数据共享同一坐标系与空间范围，确保"点风险区 → 多源联动"成立。
坐标约定：
  工程局部坐标系 (X 米 向东, Y 米 向北)，区域 1000m × 800m
  线路沿 X 方向展布，里程 K12+000 -> K13+000 对应 X = 0 -> 1000m
"""
import os
import json
import math
import struct
import csv
from io import BytesIO

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch
from PIL import Image, ImageDraw, ImageFilter

try:
    from osgeo import gdal
    HAVE_GDAL = True
except Exception:
    HAVE_GDAL = False

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")
for sub in ["dem", "orthophoto", "pointcloud", "geophysics", "boreholes", "report"]:
    os.makedirs(os.path.join(DATA, sub), exist_ok=True)

# ----------------------------------------------------------------------------
# 区域与坐标系参数
# ----------------------------------------------------------------------------
REGION_W = 1000          # 米，东西向
REGION_H = 800           # 米，南北向
CELL = 2.0               # DEM 分辨率 2m/像素
NCOLS = int(REGION_W / CELL)  # 500
NROWS = int(REGION_H / CELL)  # 400
ORIGIN_X = 500000.0      # 假设高斯坐标原点（仅做 GeoTIFF 标定）
ORIGIN_Y = 3400000.0
PIXEL = CELL

# 隧道线路：沿 X 方向，纵坐标在 Y=400m(中线) 附近小幅度起伏，代表山区展线
def route_y(x):
    """线路中线 Y 坐标（米），随里程缓慢起伏。"""
    return 400.0 + 30.0 * math.sin(2 * math.pi * x / 900.0)

# ----------------------------------------------------------------------------
# 地形（DEM）生成：基岩 + 山脊 + 两条冲沟 + 一个滑坡迹象 + 洞口开挖区
# ----------------------------------------------------------------------------
def build_dem():
    x = np.linspace(0, REGION_W, NCOLS)
    y = np.linspace(0, REGION_H, NROWS)
    X, Y = np.meshgrid(x, y)
    # 基岩：缓倾地形，南高北低
    Z = 920.0 + 0.18 * (REGION_H - Y) + 0.05 * X
    # 山脊（线路南侧，Y≈600 一带）
    ridge = 60.0 * np.exp(-((Y - 600.0) ** 2) / (2 * 70.0 ** 2))
    Z += ridge
    # 第二条山脊（北侧远处）
    Z += 40.0 * np.exp(-((Y - 120.0) ** 2) / (2 * 60.0 ** 2))
    # 冲沟1：在 K12+200 附近斜穿，发育明显（风险相关）
    gully1 = -22.0 * np.exp(-((X - 200.0) ** 2) / (2 * 45.0 ** 2)
                             - ((Y - 470.0) ** 2) / (2 * 120.0 ** 2))
    Z += gully1
    # 冲沟2：K12+700 汇水
    gully2 = -16.0 * np.exp(-((X - 700.0) ** 2) / (2 * 55.0 ** 2)
                             - ((Y - 380.0) ** 2) / (2 * 90.0 ** 2))
    Z += gully2
    # 滑坡迹象：K12+380~480 南侧边坡，地形上呈圈椅状（中间凹、两侧凸）
    cx, cy = 430.0, 560.0
    d2 = (X - cx) ** 2 + (Y - cy) ** 2
    landslide = -25.0 * np.exp(-d2 / (2 * 90.0 ** 2))
    # 圈椅两侧隆起
    landslide += 12.0 * np.exp(-(((X - cx) - 70.0) ** 2) / (2 * 35.0 ** 2)
                                - ((Y - cy) ** 2) / (2 * 70.0 ** 2))
    landslide += 12.0 * np.exp(-(((X - cx) + 70.0) ** 2) / (2 * 35.0 ** 2)
                                - ((Y - cy) ** 2) / (2 * 70.0 ** 2))
    Z += landslide
    # 洞口开挖：K13+000 端，地表被削平
    portal = -8.0 * np.exp(-((X - 985.0) ** 2) / (2 * 25.0 ** 2)
                            - ((Y - route_y(985.0)) ** 2) / (2 * 18.0 ** 2))
    Z += portal
    # 细微噪声
    rng = np.random.default_rng(42)
    Z += rng.normal(0, 0.4, Z.shape)
    return X, Y, Z

X, Y, Z = build_dem()

# ----------------------------------------------------------------------------
# 风险对象定义（工程语义标签 + 空间范围 + 多源证据）
# 这是整个系统的"语义骨架"。
# ----------------------------------------------------------------------------
RISK_OBJECTS = [
    {
        "id": "R001",
        "name": "K12+380 洞口段边坡失稳区",
        "mileage": "K12+380",
        "mileage_m": 12380.0,
        "type": "slope_instability",
        "type_cn": "洞口边坡失稳",
        "risk_level": "高",
        "confidence": "高",
        "polygon_xy": [[360, 500], [510, 500], [520, 640], [350, 640]],
        "center_xy": [430, 565],
        "evidence": {
            "image": "冲沟发育、坡面大面积裸露岩土、圈椅状地形痕迹；植被不连续",
            "pointcloud": "最大坡度约 38°，相对高差约 52m，坡面存在拉裂陡坎",
            "geophysics": "高密度电法剖面 H1-H1'：浅部存在低阻异常带 (ρ<200Ω·m)，推断为含水松动岩体",
            "borehole": "ZK3 揭示：0-8m 为碎裂状强风化花岗岩，8-15m 弱风化含裂隙水",
            "report": "《XX隧道工程地质勘察报告》6.3 节：该洞口段边坡存在卸荷裂隙与古滑坡迹象，雨季易发生表层滑塌",
            "params": {"max_slope_deg": 38, "relief_m": 52, "rho_min": 180, "weathered_depth_m": 8}
        },
        "interpretation": (
            "该区位于隧道进口段，正射影像显示冲沟发育、坡面裸露、圈椅状地貌；"
            "三维点云提取最大坡度 38°、相对高差 52m，存在拉裂陡坎；"
            "高密度电法 H1-H1' 剖面浅部低阻异常 (180Ω·m)，钻孔 ZK3 揭示 0-8m 强风化碎裂花岗岩并含裂隙水；"
            "勘察报告明确指出存在卸荷裂隙与古滑坡迹象。综合判定为洞口边坡失稳高风险，"
            "建议：① 进洞前进行边坡刷方减载与锚网喷支护；② 完善截排水天沟与坡面排水；"
            "③ 施工期加强坡体水平位移与深部位移监测，必要时增设抗滑桩。"
        ),
        "design_suggestion": "建议洞口采用长管棚超前支护 + 边坡锚网喷 + 截排水天沟，"
                            "坡脚布设 3 根抗滑桩 (1.5m×2m，桩长 18m)；施工期监测水平位移阈值 10mm。",
        "geophysics_line": "L1",
        "borehole_ids": ["ZK3", "ZK4"]
    },
    {
        "id": "R002",
        "name": "K12+720 富水破碎带",
        "mileage": "K12+720",
        "mileage_m": 12720.0,
        "type": "water_rich_fracture",
        "type_cn": "富水破碎带",
        "risk_level": "中高",
        "confidence": "中高",
        "polygon_xy": [[660, 320], [780, 320], [790, 440], [650, 440]],
        "center_xy": [720, 380],
        "evidence": {
            "image": "植被异常茂密、地形低洼汇水，可见季节性水系汇集",
            "pointcloud": "地形低洼带，相对周边低约 6-8m，呈沟槽状",
            "geophysics": "高密度电法剖面 L2-L2'：深部存在明显低阻带 (ρ<150Ω·m)，宽度约 25m，推断含水破碎带",
            "borehole": "ZK6 揭示：地下水位埋深 2.1m，15-22m 段岩芯破碎 RQD<25%，渗透系数偏大",
            "report": "《XX隧道工程地质勘察报告》7.1 节：该段存在富水构造，施工可能发生突水突泥风险",
            "params": {"rho_min": 130, "water_depth_m": 2.1, "fracture_width_m": 25, "rqd_pct": 22}
        },
        "interpretation": (
            "该区位于隧道洞身浅埋段，影像显示植被异常茂密、地形低洼汇水；"
            "点云显示沟槽状低洼地貌；高密度电法 L2-L2' 剖面深部存在宽约 25m 低阻带 (130Ω·m)；"
            "钻孔 ZK6 揭示地下水位埋深仅 2.1m，15-22m 岩芯破碎 RQD=22%；"
            "勘察报告提示突水突泥风险。综合判定为富水破碎带中高风险，"
            "建议：① 超前地质预报 (TSP + 地质雷达 + 超前钻孔) 全过程跟进；"
            "② 超前帷幕注浆封堵地下水；③ 备用抽排水能力 ≥200m³/h；④ 设置防水闸门。"
        ),
        "design_suggestion": "建议采用超前帷幕注浆 (加固圈 5m) + 双层初期支护，预留注浆管；"
                            "施工配备 200m³/h 抽排水能力，洞口设防水闸门。",
        "geophysics_line": "L2",
        "borehole_ids": ["ZK6"]
    },
    {
        "id": "R003",
        "name": "K12+050 缓坡松散堆积区",
        "mileage": "K12+050",
        "mileage_m": 12050.0,
        "type": "loose_deposit",
        "type_cn": "松散堆积",
        "risk_level": "中",
        "confidence": "中",
        "polygon_xy": [[10, 350], [120, 350], [130, 470], [5, 470]],
        "center_xy": [65, 410],
        "evidence": {
            "image": "扇形堆积地貌，植被稀疏，色调浅",
            "pointcloud": "坡度平缓 (8-12°)，表面起伏，堆积特征明显",
            "geophysics": "剖面 L3-L3'：表层视电阻率梯度变化，浅部松散层厚约 6-9m",
            "borehole": "ZK1 揭示：0-7m 为碎石土堆积，下伏基岩面起伏",
            "report": "报告 5.2 节：隧道出口段覆盖层为坡洪积碎石土，承载力较低",
            "params": {"avg_slope_deg": 10, "deposit_depth_m": 7}
        },
        "interpretation": (
            "该区为隧道出口段缓坡，影像显示扇形堆积地貌、植被稀疏；"
            "点云显示坡度平缓 (8-12°)、表面起伏；物探反映浅部松散层厚 6-9m；"
            "钻孔 ZK1 揭示 0-7m 碎石土堆积。综合判定为松散堆积中风险，"
            "建议：明洞段基础采用换填或钻孔灌注桩，避免不均匀沉降。"
        ),
        "design_suggestion": "明洞基础采用 1.5m 换填碎石 + φ1.2m 钻孔灌注桩 (间距 4m，嵌岩 3m)。",
        "geophysics_line": "L3",
        "borehole_ids": ["ZK1"]
    }
]

# ----------------------------------------------------------------------------
# 线路 / 里程
# ----------------------------------------------------------------------------
ROUTE = {
    "type": "tunnel",
    "name": "XX 铁路隧道 (K12+000 ~ K13+000)",
    "start_mileage": "K12+000",
    "end_mileage": "K13+000",
    "portal_in": {"mileage": "K12+000", "xy": [0.0, route_y(0.0)], "label": "出口/明洞口"},
    "portal_out": {"mileage": "K13+000", "xy": [1000.0, route_y(1000.0)], "label": "进口/洞口"},
    # 每 50m 一个轴线点
    "centerline": [
        {"mileage_m": 12000 + i * 50, "xy": [i * 50, route_y(i * 50)]}
        for i in range(21)
    ]
}

# ----------------------------------------------------------------------------
# 钻孔
# ----------------------------------------------------------------------------
BOREHOLES = [
    {"id": "ZK1", "xy": [55, 405], "mileage": "K12+050", "elevation": 995.2,
     "depth_m": 18.0, "water_depth_m": 6.5,
     "layers": [
        {"top": 0, "bottom": 4, "lithology": "种植土", "color": "#6b4f2a", "desc": "褐色，松散，含植物根系"},
        {"top": 4, "bottom": 7, "lithology": "碎石土", "color": "#a08060", "desc": "坡洪积，稍密，碎石含量约60%"},
        {"top": 7, "bottom": 12, "lithology": "全风化花岗岩", "color": "#c8a878", "desc": "呈砂土状，可塑"},
        {"top": 12, "bottom": 18, "lithology": "弱风化花岗岩", "color": "#8a8a90", "desc": "岩体较完整，RQD=65%"}
     ]},
    {"id": "ZK2", "xy": [180, 462], "mileage": "K12+180", "elevation": 1012.4,
     "depth_m": 22.0, "water_depth_m": None,
     "layers": [
        {"top": 0, "bottom": 3, "lithology": "粉质粘土", "color": "#7a5a3a", "desc": "硬塑，含少量碎石"},
        {"top": 3, "bottom": 22, "lithology": "弱风化花岗岩", "color": "#8a8a90", "desc": "岩体较完整，节理不发育"}
     ]},
    {"id": "ZK3", "xy": [410, 560], "mileage": "K12+380", "elevation": 1048.6,
     "depth_m": 25.0, "water_depth_m": 8.2,
     "layers": [
        {"top": 0, "bottom": 2, "lithology": "坡积碎石", "color": "#a08060", "desc": "松散，含块石"},
        {"top": 2, "bottom": 8, "lithology": "强风化碎裂花岗岩", "color": "#b89868", "desc": "碎裂结构，裂隙发育，含裂隙水"},
        {"top": 8, "bottom": 15, "lithology": "弱风化花岗岩", "color": "#8a8a90", "desc": "节理较发育，RQD=45%"},
        {"top": 15, "bottom": 25, "lithology": "微风化花岗岩", "color": "#707078", "desc": "岩体完整，RQD=80%"}
     ]},
    {"id": "ZK4", "xy": [475, 600], "mileage": "K12+450", "elevation": 1065.1,
     "depth_m": 23.0, "water_depth_m": 9.0,
     "layers": [
        {"top": 0, "bottom": 3, "lithology": "含碎石粉质粘土", "color": "#7a5a3a", "desc": "稍湿，可塑"},
        {"top": 3, "bottom": 9, "lithology": "强风化花岗岩", "color": "#b89868", "desc": "碎裂状，含卸荷裂隙"},
        {"top": 9, "bottom": 16, "lithology": "弱风化花岗岩", "color": "#8a8a90", "desc": "节理发育，RQD=50%"},
        {"top": 16, "bottom": 23, "lithology": "微风化花岗岩", "color": "#707078", "desc": "完整，RQD=82%"}
     ]},
    {"id": "ZK5", "xy": [620, 350], "mileage": "K12+620", "elevation": 1003.7,
     "depth_m": 20.0, "water_depth_m": None,
     "layers": [
        {"top": 0, "bottom": 4, "lithology": "粉质粘土", "color": "#7a5a3a", "desc": "硬塑"},
        {"top": 4, "bottom": 20, "lithology": "弱风化花岗岩", "color": "#8a8a90", "desc": "较完整，RQD=70%"}
     ]},
    {"id": "ZK6", "xy": [715, 385], "mileage": "K12+720", "elevation": 998.3,
     "depth_m": 28.0, "water_depth_m": 2.1,
     "layers": [
        {"top": 0, "bottom": 3, "lithology": "粉质粘土", "color": "#7a5a3a", "desc": "饱和，软塑"},
        {"top": 3, "bottom": 8, "lithology": "全风化花岗岩", "color": "#c8a878", "desc": "砂土状，饱水"},
        {"top": 8, "bottom": 15, "lithology": "弱风化花岗岩", "color": "#8a8a90", "desc": "节理发育"},
        {"top": 15, "bottom": 22, "lithology": "破碎带", "color": "#5a4030", "desc": "构造角砾岩，RQD=22%，富水"},
        {"top": 22, "bottom": 28, "lithology": "弱风化花岗岩", "color": "#8a8a90", "desc": "较完整"}
     ]}
]

# ----------------------------------------------------------------------------
# 物探测线 (高密度电法) —— 三条线，对应三个风险区
# ----------------------------------------------------------------------------
GEOPHYSICS_LINES = [
    {"id": "L1", "name": "H1-H1' 洞口边坡剖面", "related_risk": "R001",
     "start_xy": [350, 500], "end_xy": [520, 640], "length_m": 220,
     "method": "高密度电法", "rho_min": 180, "anomaly_depth_m": 8},
    {"id": "L2", "name": "H2-H2' 富水破碎带剖面", "related_risk": "R002",
     "start_xy": [650, 320], "end_xy": [790, 440], "length_m": 185,
     "method": "高密度电法", "rho_min": 130, "anomaly_depth_m": 18},
    {"id": "L3", "name": "H3-H3' 松散堆积剖面", "related_risk": "R003",
     "start_xy": [10, 350], "end_xy": [130, 470], "length_m": 165,
     "method": "高密度电法", "rho_min": 280, "anomaly_depth_m": 7}
]


# ----------------------------------------------------------------------------
# 1) 写出 DEM：GeoTIFF（若 GDAL 可用）+ PNG + .tfw + 头信息
# ----------------------------------------------------------------------------
def write_dem():
    # 归一化为 PNG（伪彩色 hillshade）
    # hillshade
    ls = _hillshade(Z, CELL)
    zmin, zmax = float(Z.min()), float(Z.max())
    norm = (Z - zmin) / (zmax - zmin)
    # 颜色映射：低处绿、中间棕、高处浅灰白
    rgb = _terrain_cmap(norm)
    # 叠加 hillshade 阴影
    shade = (ls - ls.min()) / (ls.max() - ls.min() + 1e-9)
    shade = np.clip(shade, 0.2, 1.0)[..., None]
    rgb = (rgb * shade * 255).astype(np.uint8)
    # 翻转南北：图片行0=北(Y大)，DEM行0=Y=0(南)
    rgb = rgb[::-1]
    Image.fromarray(rgb).save(os.path.join(DATA, "dem", "dem.png"))

    # GeoTIFF
    if HAVE_GDAL:
        drv = gdal.GetDriverByName("GTiff")
        ds = drv.Create(os.path.join(DATA, "dem", "dem.tif"), NCOLS, NROWS, 1, gdal.GDT_Float32)
        gt = (ORIGIN_X, CELL, 0, ORIGIN_Y + REGION_H, 0, -CELL)
        ds.SetGeoTransform(gt)
        ds.GetRasterBand(1).WriteArray(Z.astype(np.float32))
        ds.FlushCache()
        ds = None

    # 元信息 JSON（前端用：地理范围、分辨率）
    meta = {
        "ncols": NCOLS, "nrows": NROWS, "cell": CELL,
        "extent": {"xmin": 0, "ymin": 0, "xmax": REGION_W, "ymax": REGION_H},
        "elevation": {"min": zmin, "max": zmax},
        "image": "dem/dem.png",
        "png_w": NCOLS, "png_h": NROWS,
        "world_file": "dem/dem.pgw"
    }
    # world file: 像素X大小, 旋转, 旋转, 像素Y大小(负), 左上X, 左上Y
    with open(os.path.join(DATA, "dem", "dem.pgw"), "w") as f:
        f.write(f"{CELL}\n0\n0\n{-CELL}\n0\n{REGION_H}\n")
    with open(os.path.join(DATA, "dem", "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _hillshade(z, cell, azimuth=315, altitude=45):
    az = math.radians(360 - azimuth)
    alt = math.radians(altitude)
    fx = (np.roll(z, -1, 1) - np.roll(z, 1, 1)) / (2 * cell)
    fy = (np.roll(z, -1, 0) - np.roll(z, 1, 0)) / (2 * cell)
    slope = np.arctan(np.sqrt(fx ** 2 + fy ** 2))
    aspect = np.arctan2(fy, -fx)
    ls = (np.cos(alt) * np.cos(slope)
          + np.sin(alt) * np.sin(slope) * np.cos(az - aspect))
    return np.clip(ls * 255, 0, 255)


def _terrain_cmap(t):
    """简单地形色带：绿→黄棕→灰白。t 形状 (H,W) 返回 (H,W,3)。"""
    t = t[..., None]
    stops = np.array([
        [0.40, 0.62, 0.30],   # 绿（低）
        [0.55, 0.70, 0.40],
        [0.78, 0.68, 0.45],   # 棕
        [0.85, 0.80, 0.72],
        [0.95, 0.95, 0.95],   # 灰白（高）
    ])
    pts = np.array([0.0, 0.25, 0.55, 0.78, 1.0])
    out = np.zeros(t.shape[:2] + (3,))
    for c in range(3):
        out[..., c] = np.interp(t[..., 0], pts, stops[:, c])
    return out


# ----------------------------------------------------------------------------
# 2) 正射影像：基于 DEM 模拟真彩色，叠加植被/水系/裸土/冲沟
# ----------------------------------------------------------------------------
def write_orthophoto():
    z = Z.copy()
    zmin, zmax = float(z.min()), float(z.max())
    nz = (z - zmin) / (zmax - zmin)

    base = _terrain_cmap(nz)  # (H,W,3)

    # 植被：在低洼、汇水区（坡度小）加绿色斑块
    fy, fx = np.gradient(z, CELL)
    slope = np.degrees(np.arctan(np.sqrt(fx ** 2 + fy ** 2)))
    rng = np.random.default_rng(7)
    veg = (slope < 15) & (z < (zmin + 0.55 * (zmax - zmin)))
    veg_noise = rng.random(z.shape) < 0.5
    veg_mask = veg & veg_noise
    base[veg_mask] = base[veg_mask] * 0.3 + np.array([0.20, 0.45, 0.18]) * 0.7

    # 富水区（K12+720 周边）植被更密
    cx2, cy2 = 720, 380
    d2 = (X - cx2) ** 2 + (Y - cy2) ** 2
    rich = d2 < 90 ** 2
    base[rich] = base[rich] * 0.2 + np.array([0.15, 0.40, 0.15]) * 0.8
    # 水系细线
    water = ((X - 700) ** 2 / 60 ** 2 + (Y - 380) ** 2 / 18 ** 2) < 1
    base[water] = np.array([0.25, 0.35, 0.55])

    # 冲沟1（K12+200）裸土浅色
    g1 = ((X - 200) ** 2 / 40 ** 2 + (Y - 470) ** 2 / 110 ** 2) < 1
    base[g1] = base[g1] * 0.4 + np.array([0.75, 0.65, 0.50]) * 0.6

    # 滑坡裸露区（R001 圈椅内）
    cx, cy = 430, 565
    d2 = (X - cx) ** 2 + (Y - cy) ** 2
    bare = (d2 < 80 ** 2) & (slope > 25)
    base[bare] = base[bare] * 0.3 + np.array([0.78, 0.66, 0.50]) * 0.7

    # 松散堆积区浅色（R003）
    d3 = (X - 65) ** 2 / 70 ** 2 + (Y - 410) ** 2 / 60 ** 2
    base[d3 < 1] = base[d3 < 1] * 0.4 + np.array([0.80, 0.72, 0.58]) * 0.6

    base = np.clip(base * 255, 0, 255).astype(np.uint8)
    base = base[::-1]  # 南北翻转
    Image.fromarray(base).save(os.path.join(DATA, "orthophoto", "orthophoto.png"))

    meta = {
        "image": "orthophoto/orthophoto.png",
        "extent": {"xmin": 0, "ymin": 0, "xmax": REGION_W, "ymax": REGION_H},
        "png_w": NCOLS, "png_h": NROWS,
        "world_file": "orthophoto/orthophoto.pgw",
        "desc": "无人机正射影像 (DOM)，分辨率 2m/像素，模拟真彩色"
    }
    with open(os.path.join(DATA, "orthophoto", "orthophoto.pgw"), "w") as f:
        f.write(f"{CELL}\n0\n0\n{-CELL}\n0\n{REGION_H}\n")
    with open(os.path.join(DATA, "orthophoto", "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# 3) 点云（PLY）：采样 DEM + 坡度着色，聚焦三个风险区加密
# ----------------------------------------------------------------------------
def write_pointcloud():
    rng = np.random.default_rng(11)
    # 全区均匀采样
    n_global = 40000
    xs = rng.uniform(0, REGION_W, n_global)
    ys = rng.uniform(0, REGION_H, n_global)
    # 在风险区加密
    for r in RISK_OBJECTS:
        cx, cy = r["center_xy"]
        pts = rng.uniform(-90, 90, (15000, 2))
        xs = np.concatenate([xs, pts[:, 0] + cx])
        ys = np.concatenate([ys, pts[:, 1] + cy])
    # 限定区域
    m = (xs >= 0) & (xs <= REGION_W) & (ys >= 0) & (ys <= REGION_H)
    xs, ys = xs[m], ys[m]
    # 高程：双线性采样 DEM
    zi = _bilinear(Z, xs, ys)
    # 坡度
    gx, gy = np.gradient(Z, CELL)
    slope_deg = np.degrees(np.arctan(np.sqrt(gx ** 2 + gy ** 2)))
    si = _bilinear(slope_deg, xs, ys)
    # 颜色：坡度越大越红
    colors = _slope_color(si)
    # 写 PLY (ascii，前端 Three.js PLYLoader 支持)
    path = os.path.join(DATA, "pointcloud", "terrain.ply")
    n = len(xs)
    with open(path, "w") as f:
        f.write("ply\nformat ascii 1.0\n")
        f.write(f"element vertex {n}\n")
        f.write("property float x\nproperty float y\nproperty float z\n")
        f.write("property uchar red\nproperty uchar green\nproperty uchar blue\n")
        f.write("end_header\n")
        # 按行写，控制内存
        for i in range(n):
            f.write(f"{xs[i]:.2f} {ys[i]:.2f} {zi[i]:.2f} {colors[i,0]} {colors[i,1]} {colors[i,2]}\n")
    meta = {
        "file": "pointcloud/terrain.ply",
        "format": "ply",
        "point_count": n,
        "extent": {"xmin": 0, "ymin": 0, "xmax": REGION_W, "ymax": REGION_H},
        "elevation_range": {"min": float(zi.min()), "max": float(zi.max())},
        "color_coding": "坡度着色 (绿=缓坡，黄=中等，红=陡坡)"
    }
    with open(os.path.join(DATA, "pointcloud", "meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _bilinear(grid, xs, ys):
    """grid 形状 (NROWS, NCOLS) 对应 Y∈[0,REGION_H] 行0=Y0；对任意 xs,ys 双线性插值。"""
    col = np.clip(xs / CELL, 0, NCOLS - 1.0001)
    row = np.clip(ys / CELL, 0, NROWS - 1.0001)
    c0 = np.floor(col).astype(int); c1 = c0 + 1
    r0 = np.floor(row).astype(int); r1 = r0 + 1
    fx = col - c0; fy = row - r0
    v = (grid[r0, c0] * (1 - fx) * (1 - fy) + grid[r0, c1] * fx * (1 - fy)
         + grid[r1, c0] * (1 - fx) * fy + grid[r1, c1] * fx * fy)
    return v


def _slope_color(slope_deg):
    s = np.clip(slope_deg / 45.0, 0, 1)
    out = np.zeros((len(s), 3))
    # 绿 -> 黄 -> 红
    out[:, 0] = np.clip(s * 2, 0, 1) * 255
    out[:, 1] = np.clip(2 - s * 2, 0, 1) * 200 + 30
    out[:, 2] = 40 * (1 - s)
    return out.astype(np.uint8)


# ----------------------------------------------------------------------------
# 4) 物探剖面：每个测线生成 2D 电阻率反演断面 (PNG + CSV)
# ----------------------------------------------------------------------------
def write_geophysics():
    rng = np.random.default_rng(3)
    out = []
    for line in GEOPHYSICS_LINES:
        # 断面：横=桩号 0..L，纵=深度 0..maxd
        nsta = 40
        ndepth = 25
        L = line["length_m"]
        maxd = 30.0
        sta = np.linspace(0, L, nsta)
        dep = np.linspace(0, maxd, ndepth)
        STA, DEP = np.meshgrid(sta, dep)
        # 背景电阻率：随深度升高
        rho = 80 + DEP * 12 + 60 * np.exp(-DEP / 6)
        # 加入目标低阻异常（垂直柱状/漏斗）
        anom_x = L / 2
        anom = -line["rho_min"] * np.exp(-((STA - anom_x) ** 2) / (2 * (line["length_m"] * 0.08) ** 2)) \
               * np.exp(-((DEP - line["anomaly_depth_m"] * 0.6) ** 2) / (2 * 8 ** 2))
        rho = rho + anom
        rho += rng.normal(0, 8, rho.shape)
        rho = np.clip(rho, 20, 1500)
        # 渲染为彩色 PNG
        fig, ax = plt.subplots(figsize=(8, 4.2), dpi=110)
        im = ax.imshow(rho, aspect="auto", origin="upper",
                       extent=[0, L, maxd, 0], cmap="jet_r",
                       vmin=50, vmax=1200)
        ax.set_xlabel("测线桩号 (m)", fontname="SimHei", fontsize=11)
        ax.set_ylabel("深度 (m)", fontname="SimHei", fontsize=11)
        ax.set_title(f"{line['name']} — {line['method']}电阻率断面",
                     fontname="SimHei", fontsize=13)
        cb = fig.colorbar(im, ax=ax, shrink=0.85)
        cb.set_label("视电阻率 (Ω·m)", fontname="SimHei")
        # 标注异常
        ax.plot([anom_x], [line["anomaly_depth_m"]], "w*", markersize=16, markeredgecolor="k")
        ax.annotate("低阻异常区", xy=(anom_x, line["anomaly_depth_m"]),
                    xytext=(anom_x + L * 0.12, line["anomaly_depth_m"] + 3),
                    fontname="SimHei", color="white", fontsize=11,
                    arrowprops=dict(arrowstyle="->", color="white"))
        # 中文字体
        for lbl in ax.get_xticklabels() + ax.get_yticklabels():
            lbl.set_fontname("SimHei")
        fig.tight_layout()
        img_path = os.path.join(DATA, "geophysics", f"{line['id']}.png")
        fig.savefig(img_path, dpi=110)
        plt.close(fig)
        # CSV（桩号,深度,电阻率）
        csv_path = os.path.join(DATA, "geophysics", f"{line['id']}.csv")
        with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.writer(f)
            wr.writerow(["station_m", "depth_m", "rho_ohm_m"])
            for i in range(ndepth):
                for j in range(nsta):
                    wr.writerow([round(sta[j], 1), round(dep[i], 1), round(rho[i, j], 1)])
        out.append({**line,
                    "image": f"geophysics/{line['id']}.png",
                    "csv": f"geophysics/{line['id']}.csv",
                    "rho_min": float(rho.min())})
    with open(os.path.join(DATA, "geophysics", "lines.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# 5) 钻孔柱状图：渲染 PNG + 导出数据 JSON
# ----------------------------------------------------------------------------
def write_boreholes():
    for bh in BOREHOLES:
        # 渲染柱状图
        fig, ax = plt.subplots(figsize=(5, max(5, bh["depth_m"] * 0.28)), dpi=110)
        y = 0
        legend_h = {}
        for layer in bh["layers"]:
            h = layer["bottom"] - layer["top"]
            ax.barh(y + h / 2, 1, height=h, color=layer["color"],
                    edgecolor="black", linewidth=0.6)
            # 填充花纹
            ax.text(0.5, y + h / 2, f"{layer['lithology']}\n({layer['top']}-{layer['bottom']}m)",
                    ha="center", va="center", fontname="SimHei", fontsize=9)
            y += h
        # 地下水位线
        if bh["water_depth_m"] is not None:
            ax.axhline(bh["water_depth_m"], color="#1f6fd8", linewidth=2, linestyle="--")
            ax.text(1.15, bh["water_depth_m"], "地下水位",
                    fontname="SimHei", color="#1f6fd8", va="center", fontsize=10)
        ax.set_xlim(0, 2)
        ax.set_ylim(bh["depth_m"], -0.5)
        ax.set_ylabel("深度 (m)", fontname="SimHei")
        ax.set_xticks([])
        ax.set_title(f"{bh['id']} 钻孔柱状图\n里程 {bh['mileage']} 孔口高程 {bh['elevation']}m",
                     fontname="SimHei", fontsize=12)
        for lbl in ax.get_yticklabels():
            lbl.set_fontname("SimHei")
        fig.tight_layout()
        img_path = os.path.join(DATA, "boreholes", f"{bh['id']}.png")
        fig.savefig(img_path, dpi=110)
        plt.close(fig)
    with open(os.path.join(DATA, "boreholes", "boreholes.json"), "w", encoding="utf-8") as f:
        json.dump(BOREHOLES, f, ensure_ascii=False, indent=2)


# ----------------------------------------------------------------------------
# 6) 勘察报告（结构化 + 文本）—— 多个段落，供 RAG/报告生成
# ----------------------------------------------------------------------------
SURVEY_REPORT = {
    "title": "XX 铁路隧道工程地质勘察报告",
    "project": "XX 铁路 K12+000 ~ K13+000 段隧道工程",
    "survey_unit": "中铁 XX 勘察设计院",
    "date": "2024-09",
    "sections": [
        {"id": "1", "title": "1 工程概况",
         "content": "本隧道为双线电气化铁路隧道，起讫里程 K12+000 ~ K13+000，全长 1000m，"
                    "最大埋深约 75m。隧道穿越低山丘陵区，地表高程 985~1075m，相对高差约 90m。"
                    "沿线植被发育，冲沟较多。"},
        {"id": "5.2", "title": "5.2 出口段 (K12+000~K12+150) 工程地质条件",
         "content": "该段为洞口明洞段，覆盖层为坡洪积碎石土，厚度 6-9m，下伏全~弱风化花岗岩。"
                    "ZK1 揭示 0-7m 碎石土堆积，承载力特征值 fak 约 220kPa。建议明洞基础采用换填或灌注桩。",
         "related_risks": ["R003"]},
        {"id": "6.3", "title": "6.3 进口洞口段 (K12+300~K12+550) 边坡稳定性",
         "content": "隧道进口 K12+380 一带边坡存在古滑坡迹象，地形呈圈椅状，坡面大面积裸露，"
                    "ZK3 揭示 0-8m 强风化碎裂花岗岩，含卸荷裂隙与裂隙水。"
                    "高密度电法 H1-H1' 剖面浅部低阻异常 (ρ<200Ω·m)，反映松动含水岩体。"
                    "综合判断该洞口边坡稳定性差，雨季存在表层滑塌甚至整体失稳风险，"
                    "建议进洞前刷方减载、锚网喷支护并完善截排水。",
         "related_risks": ["R001"]},
        {"id": "7.1", "title": "7.1 洞身 K12+650~K12+800 富水破碎带",
         "content": "K12+720 一带高密度电法 H2-H2' 剖面深部出现宽约 25m 低阻带 (ρ<150Ω·m)，"
                    "ZK6 揭示地下水位埋深 2.1m，15-22m 构造角砾岩 RQD<25%，渗透性较好。"
                    "判断为富水破碎带，隧道施工存在突水突泥风险，建议超前地质预报与帷幕注浆。",
         "related_risks": ["R002"]},
        {"id": "8", "title": "8 结论与建议",
         "content": "全线主要风险：① K12+380 洞口边坡失稳 (高)；② K12+720 富水破碎带突水 (中高)；"
                    "③ K12+050 松散堆积段基础沉降 (中)。建议分段采取针对性工程措施，"
                    "施工期建立监控量测体系，动态调整支护参数。"}
    ]
}


def write_report():
    with open(os.path.join(DATA, "report", "survey_report.json"), "w", encoding="utf-8") as f:
        json.dump(SURVEY_REPORT, f, ensure_ascii=False, indent=2)
    # 纯文本版（RAG 切片友好）
    lines = [SURVEY_REPORT["title"], "=" * 40, ""]
    for s in SURVEY_REPORT["sections"]:
        lines.append(s["title"])
        lines.append(s["content"])
        lines.append("")
    with open(os.path.join(DATA, "report", "survey_report.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ----------------------------------------------------------------------------
# 7) 风险证据链表 + 线路 + 项目元信息 —— 汇总成 manifest.json
# ----------------------------------------------------------------------------
def write_manifest():
    manifest = {
        "project": {
            "name": "多源勘察数据联动展示与证据链追溯系统",
            "subtitle": "空天地多源勘察数据融合展示与风险证据链决策平台",
            "scenario": "XX 铁路隧道 K12+000 ~ K13+000 (示范案例)",
            "coordinate_note": "工程局部坐标系 (X 米向东, Y 米向北)，区域 1000m × 800m",
            "mileage_note": "里程 K12+000~K13+000 对应 X = 0~1000m"
        },
        "route": ROUTE,
        "dem": {"meta": "dem/meta.json", "image": "dem/dem.png"},
        "orthophoto": {"meta": "orthophoto/meta.json", "image": "orthophoto/orthophoto.png"},
        "pointcloud": {"meta": "pointcloud/meta.json", "file": "pointcloud/terrain.ply"},
        "geophysics_lines": "geophysics/lines.json",
        "boreholes": "boreholes/boreholes.json",
        "report": "report/survey_report.json",
        "risk_objects": RISK_OBJECTS,
        "data_sources": [
            {"type": "正射影像/卫星影像", "icon": "image", "purpose": "地表环境、地貌、植被、水系判断",
             "file": "orthophoto/orthophoto.png"},
            {"type": "三维点云/DEM", "icon": "mountain", "purpose": "坡度、高差、坡面形态、地形突变",
             "file": "pointcloud/terrain.ply"},
            {"type": "线路/里程数据", "icon": "route", "purpose": "把所有数据统一到工程对象上",
             "file": "manifest.json#route"},
            {"type": "物探剖面", "icon": "wave", "purpose": "低阻异常、破碎带、含水异常",
             "file": "geophysics/lines.json"},
            {"type": "钻孔资料", "icon": "drill", "purpose": "地层、岩性、地下水、破碎程度验证",
             "file": "boreholes/boreholes.json"},
            {"type": "勘察报告/文本", "icon": "doc", "purpose": "风险描述、设计建议、支护要求",
             "file": "report/survey_report.json"},
            {"type": "风险标注", "icon": "warning", "purpose": "核心案例，作为多源证据链载体",
             "file": "manifest.json#risk_objects"}
        ]
    }
    with open(os.path.join(DATA, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print("✓ manifest.json 写入完成，包含", len(RISK_OBJECTS), "个风险对象")


if __name__ == "__main__":
    print("=" * 60)
    print("开始生成多源勘察样例数据...")
    print("=" * 60)
    print("[1/7] 生成 DEM (数字高程模型)...")
    write_dem();     print("    GDAL 可用:", HAVE_GDAL)
    print("[2/7] 生成正射影像 (DOM)...")
    write_orthophoto()
    print("[3/7] 生成三维点云 (PLY)...")
    write_pointcloud()
    print("[4/7] 生成物探剖面 (高密度电法)...")
    write_geophysics()
    print("[5/7] 生成钻孔柱状图...")
    write_boreholes()
    print("[6/7] 生成勘察报告...")
    write_report()
    print("[7/7] 汇总 manifest.json (风险证据链表)...")
    write_manifest()
    print("=" * 60)
    print("✓ 全部数据生成完成！位置:", DATA)
    # 统计
    import os.path as op
    for root, dirs, files in os.walk(DATA):
        for fn in files:
            p = op.join(root, fn)
            print(f"   {op.relpath(p, DATA):40s}  {op.getsize(p)//1024:8d} KB")
