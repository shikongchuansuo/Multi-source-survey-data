# -*- coding: utf-8 -*-
"""
处置建议规则引擎
================
按风险类型(type) + 等级(risk_level) 给出差异化处置建议文本。
从 report_gen.py 抽出为独立模块，供报告生成与跨模态探针(fusion_probe.py)
共用同一套规则——两者对同一风险类型给出的建议措辞必须一致，不能各写一份。

新增风险类型时只需在 RULES 追加一项；无需改动调用方。
"""
from typing import Any, Dict, List

# 每种风险类型一套处置策略；每条策略内按 risk_level 给出差异化措辞。
# 里程/类型等具体值在调用时从风险对象/探针证据取，避免写死在源码里。
RULES: Dict[str, Dict[str, Any]] = {
    "slope_instability": {
        "title": "洞口边坡失稳",
        "by_level": {
            "高": [
                "进洞前必须完成边坡处治：长管棚超前支护 + 锚网喷 + 截排水天沟，坡脚设抗滑桩。",
                "超前地质预报全程跟进：TSP + 地质雷达 + 超前钻孔，确认松动岩体范围。",
                "建立坡体位移监测，变形速率预警值按 {weathered_depth_m}m 风化层深度动态核定。",
            ],
            "中高": [
                "洞口段加强支护：管棚 + 锚网喷，跟进截排水措施。",
                "施工期坡体位移监测，动态调整支护参数。",
            ],
            "中": [
                "常规锚网喷支护，做好截排水。",
                "施工期位移监测。",
            ],
        },
    },
    "water_rich_fracture": {
        "title": "富水破碎带",
        "by_level": {
            "高": [
                "超前帷幕注浆 (加固圈 ≥5m) + 双层初期支护，预留注浆管。",
                "备用抽排水能力 ≥200m³/h，富水段设置防水闸门。",
                "超前预报锁定破碎带宽度 (现估 {fracture_width_m}m) 与渗透性。",
            ],
            "中高": [
                "超前帷幕注浆 + 双层初期支护，预留注浆管。",
                "施工配备抽排水能力 ≥200m³/h，设置防水闸门。",
                "超前地质预报 (TSP + 地质雷达 + 超前钻孔) 锁定破碎带宽度 (现估 {fracture_width_m}m)。",
            ],
            "中": [
                "加强初期支护，做好排水预案。",
                "超前预报确认富水性。",
            ],
        },
    },
    "loose_deposit": {
        "title": "松散堆积",
        "by_level": {
            "高": [
                "明洞基础换填碎石，钻孔灌注桩嵌岩穿过堆积层 (现估 {deposit_depth_m}m)。",
                "基础沉降监测，控制桩间距与嵌岩深度。",
                "做好地表截排水，防止堆积层进一步软化。",
            ],
            "中高": [
                "基础换填 + 灌注桩嵌岩，穿过堆积层 (现估 {deposit_depth_m}m)。",
                "基础沉降监测。",
            ],
            "中": [
                "基础换填处理，控制沉降。",
                "施工期沉降监测。",
            ],
        },
    },
}
# 兜底策略：未登记类型按等级给通用建议
FALLBACK: Dict[str, List[str]] = {
    "高": ["进洞前完成专项处治；超前地质预报全程跟进；监控量测体系到位。"],
    "中高": ["加强支护与超前预报；施工期监控量测。"],
    "中": ["按常规措施处理；施工期监测。"],
}

# 优先级排序：高风险优先处置
PRIORITY_ORDER = ["高", "中高", "中"]


def fmt_bullets(bullets: List[str], params: Dict[str, Any]) -> List[str]:
    """用 evidence.params (或探针证据参数) 填充建议里的 {占位符}，缺失占位符原样保留。"""
    out = []
    for b in bullets:
        try:
            out.append(b.format(**params) if params else b)
        except (KeyError, IndexError):
            out.append(b)
    return out


def bullets_for(rtype: str, level: str, params: Dict[str, Any]) -> List[str]:
    """风险类型 + 等级 -> 格式化后的处置建议要点（未登记类型走兜底）。"""
    rule = RULES.get(rtype, {})
    raw = rule.get("by_level", {}).get(level) or FALLBACK.get(level, FALLBACK["中"])
    return fmt_bullets(raw, params)
