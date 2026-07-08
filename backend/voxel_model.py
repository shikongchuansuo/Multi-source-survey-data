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
  2. **反演模型**：目录不存在时，**基于真实钻孔分层数据 + 物探电阻率
     在线反演**一套三维地质体——地层界面由钻孔 RBF 空间插值得到，
     富水破碎带由物探低阻异常识别，保证结果由实测数据驱动而非预设。

输出统一为工程坐标系（X 0~1000, Y 0~800, Z=绝对高程），
data 为 flat 数组，索引 index = (iz*ny + iy)*nx + ix（X 变化最快）。
前端渲染时坐标减 coord_offset 与点云对齐。
"""
import base64
import csv
import json
import math
import os

import numpy as np

import ontology
import structures3d

HERE = os.path.dirname(os.path.abspath(__file__))
GEOMODEL_DIR = os.path.join(HERE, "data", "geology_model")

# 体素总量上限（超出则自动降采样，保证前端 WebGL 流畅）
MAX_CELLS = 400_000

# 体素类别表 = 领域本体的岩性概念（单一语义来源：钻孔映射、
# 体素编码、前端图例、探针语义共用 data/ontology/geology_ontology.json）
DEMO_CATEGORIES = ontology.voxel_categories()

NODATA = -1

# 岩性归一化：钻孔异构命名 → 本体概念 code（本体别名匹配，长别名优先）
_classify_lithology = ontology.classify_lithology


# 地层界面阈值：某钻孔若缺少该风化带，用邻层推断时的缺省厚度
# （仅在极个别钻孔无某层时兜底，绝大多数钻孔有完整分带）
_DEFAULT_T = {"cover": 4.0, "full": 10.0, "high": 18.0, "mid": 26.0}


def _borehole_interface_depths(b):
    """从单个钻孔提取 4 个地层界面的埋深（米，从地表起算）。

    返回 dict: cover(覆盖层底)/full(全风化底)/high(强风化底)/mid(中风化底)。
    界面定义：取该类别及其以上所有层的累计厚度作为该界面的深度。
    若钻孔未揭露某风化带（如 ZK2 缺全/强风化），用缺省值兜底并标记缺测。
    """
    layers = b["layers"]
    # 自顶向下累计厚度，按归一化类别分组取底界
    acc = 0.0
    seen = {}
    for L in layers:
        code = _classify_lithology(L["lithology"])
        thick = L["bottom"] - L["top"]
        if code is None or code == 5:   # 破碎带不参与层序界面
            acc += thick
            continue
        acc += thick
        seen[code] = acc                 # 该类底界 = 当前累计深度

    # 层序界面：cover=类0底, full=类1底, high=类2底, mid=类3底
    # 缺失的层用下一已知层的底界（即本层厚度视为0）兜底，保证界面单调
    def _get(codes, default):
        for c in codes:
            if c in seen:
                return seen[c]
        return default

    cover = _get([0], _DEFAULT_T["cover"])
    full = _get([1], max(cover, _DEFAULT_T["full"]))
    high = _get([2], max(full, _DEFAULT_T["high"]))
    mid = _get([3], max(high, _DEFAULT_T["mid"]))
    # 单调性保险（界面应递增）
    full = max(full, cover + 0.5)
    high = max(high, full + 0.5)
    mid = max(mid, high + 0.5)
    return {"cover": cover, "full": full, "high": high, "mid": mid}


# ----------------------------------------------------------------
# 钻孔驱动的地层界面空间插值（RBF 径向基函数）
# ----------------------------------------------------------------
def _interp_surface(samples_xy, samples_v, grid_xy):
    """二维 RBF 空间插值单个地层界面。

    samples_xy: (n,2) 钻孔 xy；samples_v: (n,) 该界面埋深；
    grid_xy: (M,2) 待插值网格点 xy。返回 (M,) 插值埋深。
    用薄板样条（thin_plate_spline）：精确通过钻孔点，整体光滑，
    对工程尺度地层界面的平缓起伏是合适假设。
    """
    from scipy.interpolate import RBFInterpolator
    rbf = RBFInterpolator(
        np.asarray(samples_xy, dtype=float),
        np.asarray(samples_v, dtype=float),
        kernel="thin_plate_spline",
        smoothing=0.0,        # 精确插值（过钻孔点）
    )
    return rbf(np.asarray(grid_xy, dtype=float))


def _build_surfaces_from_boreholes(xc, yc):
    """从真实钻孔分层插值出 4 个地层界面埋深网格。

    xc/yc: 体素列中心坐标（1D）。返回 4 个 (ny,nx) 网格：
    t_cover / t_full / t_high / t_mid，单位米（地表以下埋深）。
    """
    bh = structures3d.BOREHOLES
    # 收集每个界面的钻孔样本点
    sxy = {"cover": [], "full": [], "high": [], "mid": []}
    sv = {"cover": [], "full": [], "high": [], "mid": []}
    for b in bh:
        bx, by = b["xy"]
        d = _borehole_interface_depths(b)
        for k in sxy:
            sxy[k].append([bx, by])
            sv[k].append(d[k])

    X, Y = np.meshgrid(xc, yc)              # X,Y: (ny,nx)
    grid_xy = np.column_stack([X.ravel(), Y.ravel()])

    out = {}
    for k in ("cover", "full", "high", "mid"):
        grid_v = _interp_surface(sxy[k], sv[k], grid_xy).reshape(X.shape)
        # 限幅：界面埋深必须在合理地质区间，防止稀疏点外推异常
        lo, hi = {"cover": (1.0, 12.0), "full": (5.0, 25.0),
                  "high": (10.0, 35.0), "mid": (15.0, 45.0)}[k]
        out["t_" + k] = np.clip(grid_v, lo, hi)
    return out["t_cover"], out["t_full"], out["t_high"], out["t_mid"]


# ----------------------------------------------------------------
# 物探电阻率软约束：低阻异常 → 富水破碎带
# ----------------------------------------------------------------
# 低阻判定阈值（Ω·m）：低于此值视为富水/破碎。取物探数据第 12 百分位，
# 低于全局中位的极低阻才判定，避免误伤正常地层。
_RHO_FRACTILE = 0.12


def _apply_geophysics_constraint(vox, surf, zc, xc, yc, dx, dy, dz):
    """用物探电阻率修正体素：低阻区标记为富水破碎带(code=5)。

    vox: (nz,ny,nx) 体素标签；surf: (ny,nx) 地表高程；
    zc: (nz,) 体素层中心高程；xc/yc: 体素列中心坐标。
    遍历每条物探测线，把其电阻率断面投影到三维体素空间。
    """
    lines_path = os.path.join(structures3d.DATA, "geophysics", "lines.json")
    if not os.path.exists(lines_path):
        return 0
    with open(lines_path, "r", encoding="utf-8") as f:
        lines = json.load(f)

    changed = 0
    for ln in lines:
        csv_path = os.path.join(structures3d.DATA, *ln["csv"].split("/"))
        if not os.path.exists(csv_path):
            continue
        stations, depths, grid = set(), set(), {}
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                s = float(row["station_m"])
                d = float(row["depth_m"])
                grid[(s, d)] = float(row["rho_ohm_m"])
                stations.add(s); depths.add(d)
        if not stations:
            continue
        stations = sorted(stations); depths = sorted(depths)
        # 低阻阈值（分位数）
        all_rho = np.array([grid[(s, d)] for s in stations for d in depths])
        rho_thr = float(np.quantile(all_rho, _RHO_FRACTILE))

        # 测线方向单位向量
        sx, sy = ln["start_xy"]; ex, ey = ln["end_xy"]
        length = math.hypot(ex - sx, ey - sy) or 1.0
        ux, uy = (ex - sx) / length, (ey - sy) / length

        # 找出低阻异常的 (桩号, 深度) 单元
        for s in stations:
            for d in depths:
                if grid[(s, d)] >= rho_thr:
                    continue
                # 该单元的工程坐标 + 高程
                px, py = sx + ux * s, sy + uy * s
                # 地表高程：直接用 DEM 双线性插值（与 surf 网格一致）
                surf_z = structures3d._elev_at(px, py)
                pz = surf_z - d
                # 影响半径：在 (px,py,pz) 周围 dx/dy/dz 邻域内改写为 code 5
                ix0 = int((px - 0) / dx)
                iy0 = int((py - 0) / dy)
                iz0 = int((pz - zc[0]) / dz + 0.5)
                rx = ry = 1   # 平面影响 ±1 格
                rz = 1        # 深度影响 ±1 格
                for iz in range(max(0, iz0 - rz), min(vox.shape[0], iz0 + rz + 1)):
                    for iy in range(max(0, iy0 - ry), min(vox.shape[1], iy0 + ry + 1)):
                        for ix in range(max(0, ix0 - rx), min(vox.shape[2], ix0 + rx + 1)):
                            # 软约束：只在基岩区(code=4)标记富水带，
                            # 保留钻孔确定的浅层风化分带
                            if vox[iz, iy, ix] == 4:
                                vox[iz, iy, ix] = 5
                                changed += 1
    return changed


# ----------------------------------------------------------------
# 反演模型：DEM 地表 + 钻孔插值层序 + 风险异常体 + 物探软约束
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

    # 各风化界面埋深（米）—— 由真实钻孔分层 RBF 空间插值得到
    t_cover, t_full, t_high, t_mid = _build_surfaces_from_boreholes(xc, yc)

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
    # 优先级说明：钻孔层序(0-4)是硬证据，风险椭球只在其范围内的"基岩区(code=4)"
    # 标记富水带(code=5)，不覆盖浅层风化分带；非富水类风险(边坡/松散)不动体素。
    anomalies = structures3d.build_3d_structures()["anomalies"]
    Z3 = np.broadcast_to(zc[:, None, None], vox.shape)
    X3 = np.broadcast_to(np.meshgrid(xc, yc)[0][None], vox.shape)
    Y3 = np.broadcast_to(np.meshgrid(xc, yc)[1][None], vox.shape)
    for a in anomalies:
        if a["type"] != "water_rich_fracture":
            continue        # 边坡失稳/松散堆积属地表风险，不改地下岩性分类
        sx_, sy_, sz_ = a["size"]
        m = (((X3 - a["x"]) / sx_) ** 2 + ((Y3 - a["y"]) / sy_) ** 2 +
             ((Z3 - a["center_z"]) / max(sz_, dz)) ** 2) <= 1.0
        vox[m & (vox == 4)] = 5   # 仅基岩区裂隙带转为富水破碎带

    # 物探电阻率软约束：低阻异常 → 富水破碎带（多源融合）
    lines_path = os.path.join(structures3d.DATA, "geophysics", "lines.json")
    geo_lines = 0
    if os.path.exists(lines_path):
        with open(lines_path, "r", encoding="utf-8") as f:
            geo_lines = len(json.load(f))
    geo_changes = _apply_geophysics_constraint(
        vox, surf, zc, xc, yc, dx, dy, dz)

    return {
        "source": "inverted",   # 由真实钻孔+物探反演，而非预设演示数据
        "shape": [nx, ny, nz],
        "spacing_m": [dx, dy, dz],
        "origin_xyz": origin,
        "nodata": NODATA,
        "data": vox.transpose(0, 1, 2).ravel().astype(int).tolist(),
        "categories": DEMO_CATEGORIES,
        # 地质依据元信息（前端忽略，供答辩/验收说明计算来源）
        "geology_source": "borehole_rbf_interpolation + geophysics_constraint",
        "borehole_count": len(structures3d.BOREHOLES),
        "method": ("地层界面由 %d 个钻孔分层 RBF(thin_plate_spline) 空间插值；"
                   "富水破碎带由 %d 条物探测线低阻异常(ρ<分位%.0f%%)识别；"
                   "风险区椭球同步叠加。") % (
                       len(structures3d.BOREHOLES), geo_lines, _RHO_FRACTILE * 100),
        "geophysics_voxels_changed": geo_changes,
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
