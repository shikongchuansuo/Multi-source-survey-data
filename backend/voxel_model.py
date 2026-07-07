# -*- coding: utf-8 -*-
"""
三维体素地质模型
================
为前端提供"连续三维地下地质结构"（体素分类体），填补钻孔/物探
离散二维资料与三维场景之间的缺口（见 docs/三维地质数据对接需求.md）。

数据来源（二选一，自动切换）：
  1. **交付数据**：``data/geology_model/`` 目录存在时，按对接文档约定
     解析 ``voxel_grid.json``（或 ``voxel.npy`` + ``meta.json``）与
     ``categories.json``、可选 ``transform.json``。
  2. **演示模型**：目录不存在时，基于 DEM 与钻孔分层规律 + 风险区
     异常体在线生成一套自洽的体素模型，保证功能可演示。

输出统一为工程坐标系（X 0~1000, Y 0~800, Z=绝对高程），
data 为 flat 数组，索引 index = (iz*ny + iy)*nx + ix（X 变化最快）。
前端渲染时坐标减 coord_offset 与点云对齐。
"""
import base64
import json
import math
import os

import numpy as np

import structures3d

HERE = os.path.dirname(os.path.abspath(__file__))
GEOMODEL_DIR = os.path.join(HERE, "data", "geology_model")

# 体素总量上限（超出则自动降采样，保证前端 WebGL 流畅）
MAX_CELLS = 400_000

# 演示模型类别表（按工程岩性惯例配色）
DEMO_CATEGORIES = [
    {"code": 0, "name_cn": "坡残积覆盖层", "name_en": "Colluvium",
     "color": "#8a6f4d"},
    {"code": 1, "name_cn": "全风化花岗岩", "name_en": "Completely Weathered",
     "color": "#c8a878"},
    {"code": 2, "name_cn": "强风化花岗岩", "name_en": "Highly Weathered",
     "color": "#a08060"},
    {"code": 3, "name_cn": "中风化花岗岩", "name_en": "Moderately Weathered",
     "color": "#8a8a90"},
    {"code": 4, "name_cn": "微风化基岩", "name_en": "Slightly Weathered",
     "color": "#5a5a5e"},
    {"code": 5, "name_cn": "富水破碎/异常带", "name_en": "Fracture Zone",
     "color": "#2878dc"},
]

NODATA = -1


# ----------------------------------------------------------------
# 演示模型：DEM 地表 + 随空间缓变的风化层序 + 风险区异常椭球
# ----------------------------------------------------------------
def _build_demo_voxels():
    dx, dy, dz = 20.0, 20.0, 4.0
    nx, ny = 50, 40                       # 覆盖 1000×800m
    z0, z1 = 880.0, 1080.0                # 高程范围
    nz = int((z1 - z0) / dz)              # 50 层
    origin = [0.0, 0.0, z0]

    # 地表高程网格（体素列中心处采样）
    xc = (np.arange(nx) + 0.5) * dx
    yc = (np.arange(ny) + 0.5) * dy
    surf = np.empty((ny, nx))
    for iy in range(ny):
        for ix in range(nx):
            surf[iy, ix] = structures3d._elev_at(xc[ix], yc[iy])

    # 各风化界面埋深（米，随空间平缓起伏，模拟真实层序侧向变化）
    X, Y = np.meshgrid(xc, yc)
    t_cover = np.clip(4.0 + 2.0 * np.sin(X / 150.0) +
                      1.5 * np.cos(Y / 110.0), 1.5, None)
    t_full = t_cover + 7.0 + 3.0 * np.sin(X / 220.0 + 1.0) \
        + 2.0 * np.cos(Y / 160.0 + 0.5)
    t_high = t_full + 12.0 + 4.0 * np.cos(X / 260.0) \
        + 3.0 * np.sin(Y / 190.0 + 1.2)
    t_mid = t_high + 18.0 + 5.0 * np.sin(X / 300.0 + 2.0)

    # 深度体：depth[iz,iy,ix] = 地表 - 体素中心高程
    zc = z0 + (np.arange(nz) + 0.5) * dz
    depth = surf[None, :, :] - zc[:, None, None]

    vox = np.full((nz, ny, nx), NODATA, dtype=np.int8)
    vox[depth > 0] = 0
    vox[depth > t_cover[None]] = 1
    vox[depth > t_full[None]] = 2
    vox[depth > t_high[None]] = 3
    vox[depth > t_mid[None]] = 4

    # 风险区异常体 → 富水破碎/异常带（与 /api/3d/structures 的椭球一致）
    anomalies = structures3d.build_3d_structures()["anomalies"]
    Z3 = np.broadcast_to(zc[:, None, None], vox.shape)
    X3 = np.broadcast_to(X[None], vox.shape)
    Y3 = np.broadcast_to(Y[None], vox.shape)
    for a in anomalies:
        sx_, sy_, sz_ = a["size"]
        m = (((X3 - a["x"]) / sx_) ** 2 + ((Y3 - a["y"]) / sy_) ** 2 +
             ((Z3 - a["center_z"]) / max(sz_, dz)) ** 2) <= 1.0
        vox[m & (vox != NODATA)] = 5

    return {
        "source": "demo",
        "shape": [nx, ny, nz],
        "spacing_m": [dx, dy, dz],
        "origin_xyz": origin,
        "nodata": NODATA,
        "data": vox.transpose(0, 1, 2).ravel().astype(int).tolist(),
        "categories": DEMO_CATEGORIES,
    }


# ----------------------------------------------------------------
# 交付数据解析（对接文档 §3 方案 A/B）
# ----------------------------------------------------------------
def _decode_data(raw, dtype, n_expected):
    """data 字段兼容 flat 整数数组 / base64 两种形式。"""
    if isinstance(raw, str):
        buf = base64.b64decode(raw)
        arr = np.frombuffer(buf, dtype=np.dtype(dtype or "int8"))
    else:
        arr = np.asarray(raw, dtype=np.int32)
    if arr.size != n_expected:
        raise ValueError(f"体素数据长度 {arr.size} != shape 乘积 {n_expected}")
    return arr


def _load_delivered():
    def _read_json(name):
        p = os.path.join(GEOMODEL_DIR, name)
        if not os.path.exists(p):
            return None
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)

    grid_json = _read_json("voxel_grid.json")
    npy_path = os.path.join(GEOMODEL_DIR, "voxel.npy")
    if grid_json is not None:
        meta = grid_json
        nx, ny, nz = meta["shape"]
        arr = _decode_data(meta["data"], meta.get("data_dtype"), nx * ny * nz)
        vox = arr.reshape(nz, ny, nx)   # 约定 index=(iz*ny+iy)*nx+ix
    elif os.path.exists(npy_path):
        meta = _read_json("meta.json") or {}
        vox = np.load(npy_path)         # 约定 shape=(nz,ny,nx)
        nz, ny, nx = vox.shape
        meta.setdefault("shape", [nx, ny, nz])
    else:
        raise FileNotFoundError("geology_model 目录缺少 voxel_grid.json / voxel.npy")

    cats = _read_json(meta.get("categories_ref", "categories.json")) \
        or _read_json("categories.json") or DEMO_CATEGORIES
    nodata = meta.get("nodata", NODATA)
    origin = list(meta.get("origin_xyz", [0.0, 0.0, 880.0]))
    spacing = list(meta.get("spacing_m", [10.0, 10.0, 1.0]))

    # 坐标变换（对接文档 §5：team = eng + d → eng = team - d）
    tf = _read_json("transform.json")
    if tf:
        origin[0] -= float(tf.get("dx", 0.0))
        origin[1] -= float(tf.get("dy", 0.0))
        origin[2] -= float(tf.get("dz", 0.0))

    return {
        "source": "delivered",
        "shape": [int(vox.shape[2]), int(vox.shape[1]), int(vox.shape[0])],
        "spacing_m": spacing,
        "origin_xyz": origin,
        "nodata": nodata,
        "data": vox.ravel().astype(int).tolist(),
        "categories": cats,
        "_vox": vox,
    }


def _downsample(model):
    """体素量超限时按步长抽稀，同步放大 spacing。"""
    nx, ny, nz = model["shape"]
    total = nx * ny * nz
    if total <= MAX_CELLS:
        model.pop("_vox", None)
        return model
    step = math.ceil((total / MAX_CELLS) ** (1.0 / 3.0))
    vox = model.pop("_vox", None)
    if vox is None:
        vox = np.asarray(model["data"], dtype=np.int32).reshape(nz, ny, nx)
    sub = vox[::step, ::step, ::step]
    model["shape"] = [int(sub.shape[2]), int(sub.shape[1]), int(sub.shape[0])]
    model["spacing_m"] = [s * step for s in model["spacing_m"]]
    model["data"] = sub.ravel().astype(int).tolist()
    model["downsample_step"] = step
    return model


def build_voxel_model():
    """构建（或解析）体素地质模型，输出前端渲染所需 JSON。"""
    if os.path.isdir(GEOMODEL_DIR):
        model = _load_delivered()
    else:
        model = _build_demo_voxels()
    model = _downsample(model)
    model["coord_offset"] = {"x": 500, "y": 400, "z": 950}
    model["note"] = ("index=(iz*ny+iy)*nx+ix；体素中心工程坐标 = "
                     "origin + (i+0.5)*spacing；渲染时减 coord_offset")
    return model


if __name__ == "__main__":
    m = build_voxel_model()
    nx, ny, nz = m["shape"]
    solid = sum(1 for v in m["data"] if v != m["nodata"])
    print(f"来源: {m['source']}  网格: {nx}×{ny}×{nz} = {nx*ny*nz:,}")
    print(f"实体体素: {solid:,}  类别: {len(m['categories'])}")
    print("✓ 体素模型构建完成")
