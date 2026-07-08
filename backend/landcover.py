# -*- coding: utf-8 -*-
"""
地物分类识别（遥感影像智能解译）
================================
对正射影像做**无监督聚类 + 规则语义标注**的地物分类：

  特征 = 影像 RGB + 过绿指数(ExG) + DEM 坡度   （图像特征 + 地形特征融合）
  聚类 = K-Means (k=5, 固定随机种子保证可复现)
  语义 = 按聚类中心的光谱/地形特征规则赋予地物类别名称

结果缓存到 ``data/landcover/``（分类图 PNG + meta.json），
删除该目录即可触发重算。对应 PPT「表示学习+特征融合 → 地物分类识别」。
"""
import json
import os

import numpy as np

import structures3d

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = structures3d.DATA
OUT_DIR = os.path.join(DATA, "landcover")
OUT_PNG = os.path.join(OUT_DIR, "landcover.png")
OUT_META = os.path.join(OUT_DIR, "meta.json")

K = 5
_SEED = 42

# 语义标注调色板（分类图渲染色，与影像区分度高）
_PALETTE = {
    "植被覆盖区": "#2f9e5f",
    "裸土/耕植区": "#c49a4a",
    "陡坡裸岩区": "#b34a3a",
    "阴影/沟谷区": "#4a5a8a",
    "道路/硬化地表": "#d8d8d0",
}


def _slope_grid():
    """DEM 坡度网格（度），与 DEM 同尺寸 (400,500)。"""
    Z = structures3d._Z
    cell = structures3d.CELL
    gy, gx = np.gradient(Z, cell)
    return np.degrees(np.arctan(np.hypot(gx, gy)))


def _label_clusters(centers):
    """按聚类中心特征给每个簇一个地物语义名称。

    centers 列: [R, G, B, ExG, slope_norm]（均已归一 0..1 量级）。
    规则打分、贪心分配，保证类别名不重复。
    """
    n = len(centers)
    rules = {
        # 名称: 得分函数（越大越像）
        "植被覆盖区": lambda c: c[3] * 3.0 + c[1] - c[4] * 0.5,
        "陡坡裸岩区": lambda c: c[4] * 3.0 - c[3],
        "阴影/沟谷区": lambda c: 1.0 - (c[0] + c[1] + c[2]),
        "道路/硬化地表": lambda c: (c[0] + c[1] + c[2]) - abs(c[0] - c[2]) * 2 - c[3] * 2 - c[4],
        "裸土/耕植区": lambda c: c[0] - c[3] + 0.5,   # 偏红棕、低绿
    }
    # 所有 (名称, 簇) 得分，贪心取最高分配
    scored = []
    for name, fn in rules.items():
        for i in range(n):
            scored.append((fn(centers[i]), name, i))
    scored.sort(reverse=True)
    names, used_i, used_n = {}, set(), set()
    for score, name, i in scored:
        if i in used_i or name in used_n:
            continue
        names[i] = name
        used_i.add(i)
        used_n.add(name)
    # 兜底（k>规则数时）
    for i in range(n):
        names.setdefault(i, f"未分类{i}")
    return names


def build_landcover(force=False):
    """执行地物分类（有缓存则直接读缓存）。返回 meta dict。"""
    if not force and os.path.exists(OUT_META) and os.path.exists(OUT_PNG):
        with open(OUT_META, "r", encoding="utf-8") as f:
            return json.load(f)

    from PIL import Image
    from sklearn.cluster import KMeans

    ortho_path = os.path.join(DATA, "orthophoto", "orthophoto.png")
    img = Image.open(ortho_path).convert("RGB")
    W, H = img.size                                # 500 x 400（2m/px）
    rgb = np.asarray(img, dtype=np.float64) / 255.0  # (H,W,3), 行0=北

    # 坡度对齐到影像网格：DEM 行0=南(Y=0)，影像行0=北 → 翻转
    slope = _slope_grid()[::-1, :]
    if slope.shape != (H, W):                      # 尺寸不一致时最近邻重采样
        ri = (np.linspace(0, slope.shape[0] - 1, H)).astype(int)
        ci = (np.linspace(0, slope.shape[1] - 1, W)).astype(int)
        slope = slope[np.ix_(ri, ci)]
    slope_n = np.clip(slope / 45.0, 0, 1)

    # 特征融合：RGB + 过绿指数 ExG + 坡度
    exg = np.clip(2 * rgb[..., 1] - rgb[..., 0] - rgb[..., 2], 0, 1)
    feat = np.column_stack([
        rgb[..., 0].ravel(), rgb[..., 1].ravel(), rgb[..., 2].ravel(),
        exg.ravel(), slope_n.ravel(),
    ])

    km = KMeans(n_clusters=K, random_state=_SEED, n_init=10)
    labels = km.fit_predict(feat).reshape(H, W)
    names = _label_clusters(km.cluster_centers_)

    # 渲染分类图（RGBA，半透明叠加用）
    out = np.zeros((H, W, 4), dtype=np.uint8)
    classes = []
    total = H * W
    for i in range(K):
        name = names[i]
        hexc = _PALETTE.get(name, "#888888")
        r, g, b = (int(hexc[j:j + 2], 16) for j in (1, 3, 5))
        mask = labels == i
        out[mask] = [r, g, b, 210]
        classes.append({
            "cluster": i, "name": name, "color": hexc,
            "area_pct": round(float(mask.sum()) / total * 100, 1),
            "mean_slope_deg": round(float(slope[mask].mean()), 1),
        })
    classes.sort(key=lambda c: -c["area_pct"])

    os.makedirs(OUT_DIR, exist_ok=True)
    Image.fromarray(out).save(OUT_PNG)
    meta = {
        "image": "landcover/landcover.png",
        "extent": {"xmin": 0, "ymin": 0, "xmax": 1000, "ymax": 800},
        "k": K,
        "features": ["R", "G", "B", "ExG过绿指数", "DEM坡度"],
        "method": "K-Means 无监督聚类(k=%d, seed=%d) + 光谱/地形规则语义标注" % (K, _SEED),
        "classes": classes,
    }
    with open(OUT_META, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return meta


if __name__ == "__main__":
    m = build_landcover(force=True)
    print(m["method"])
    for c in m["classes"]:
        print(f"  {c['name']}: {c['area_pct']}%  平均坡度 {c['mean_slope_deg']}°")
