# -*- coding: utf-8 -*-
"""
勘察设计领域本体
================
加载 ``data/ontology/geology_ontology.json``，提供：
  - 岩性命名归一化（钻孔异构命名 → 本体概念，实例映射）
  - 体素类别表（体素模型的类别编码直接来自本体，单一语义来源）
  - 本体实例化映射统计（/api/ontology，展示"语义一致性关联机制"）

设计对应 PPT「基于勘察设计领域本体的语义融合：
多模态特征表示学习 → 本体实例化映射关联 → 实例数据关联组合」。
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ONTOLOGY_PATH = os.path.join(HERE, "data", "ontology", "geology_ontology.json")

_ONT = None


def load_ontology():
    """加载并缓存本体。"""
    global _ONT
    if _ONT is None:
        with open(ONTOLOGY_PATH, "r", encoding="utf-8") as f:
            _ONT = json.load(f)
    return _ONT


def lithology_concepts():
    """岩性概念列表（按 code 排序）。"""
    return sorted(load_ontology()["lithology"], key=lambda c: c["code"])


def voxel_categories():
    """体素类别编码表（供 voxel_model / 前端图例使用）。"""
    return [{"code": c["code"], "name_cn": c["name_cn"],
             "name_en": c["name_en"], "color": c["color"]}
            for c in lithology_concepts()]


def classify_lithology(name):
    """岩性命名 → 本体概念 code（别名子串匹配，长别名优先）。

    未命中返回 None，交由调用方处理。
    """
    matches = []
    for c in load_ontology()["lithology"]:
        for alias in c["aliases"]:
            if alias in name:
                matches.append((len(alias), c["code"]))
    if not matches:
        return None
    # 长别名优先：如"全风化花岗岩"应命中"全风化"而不是"花岗岩"泛称
    return max(matches)[1]


def lithology_info(code):
    """code → 本体概念完整信息（含工程性质/围岩等级）。"""
    for c in load_ontology()["lithology"]:
        if c["code"] == code:
            return c
    return None


def risk_type_info(rtype):
    """风险类型 → 本体定义（证据模态 + 关键参数）。"""
    for r in load_ontology()["risk_types"]:
        if r["type"] == rtype:
            return r
    return None


def build_instance_mapping():
    """本体实例化映射：把钻孔分层实例逐条映射到本体概念。

    返回映射明细 + 覆盖率统计，供 /api/ontology 展示
    "多源异构数据 → 领域本体"的语义一致性关联结果。
    """
    import structures3d
    ont = load_ontology()
    rows = []
    hit = 0
    for b in structures3d.BOREHOLES:
        for L in b["layers"]:
            code = classify_lithology(L["lithology"])
            info = lithology_info(code) if code is not None else None
            rows.append({
                "borehole": b["id"],
                "instance": L["lithology"],
                "depth": [L["top"], L["bottom"]],
                "code": code,
                "concept": info["concept"] if info else None,
                "name_cn": info["name_cn"] if info else None,
            })
            if code is not None:
                hit += 1
    return {
        "ontology": ont,
        "instances": {
            "borehole_layers": rows,
            "total": len(rows),
            "mapped": hit,
            "coverage_pct": round(hit / max(1, len(rows)) * 100, 1),
        },
        "note": "钻孔岩性实例 → 本体概念映射；体素类别/报告术语/探针语义共用同一本体",
    }


if __name__ == "__main__":
    m = build_instance_mapping()
    print(f"本体概念: {len(m['ontology']['lithology'])} 类岩性, "
          f"{len(m['ontology']['risk_types'])} 类风险")
    print(f"钻孔层实例映射: {m['instances']['mapped']}/{m['instances']['total']} "
          f"({m['instances']['coverage_pct']}%)")
    for r in m["instances"]["borehole_layers"]:
        flag = "OK" if r["code"] is not None else "!! 未命中"
        print(f"  {r['borehole']} {r['instance']} -> {r['name_cn']} [{flag}]")
