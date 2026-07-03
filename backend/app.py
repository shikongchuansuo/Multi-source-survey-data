# -*- coding: utf-8 -*-
"""
多源勘察数据联动展示与证据链追溯系统 —— 后端 API
===================================================
基于 FastAPI 提供：
  - 静态资源服务 (DEM / 正射影像 / 点云 / 物探 / 钻孔 / 报告 / 前端页面)
  - /api/manifest          总览 (线路、风险对象、数据源清单)
  - /api/risk/{id}         风险对象详情 (多源证据)
  - /api/risk/{id}/geo     风险对象相关空间要素 (供前端高亮联动)
  - /api/boreholes         钻孔列表/详情
  - /api/geophysics/{lid}  物探剖面
  - /api/qa                证据链问答 (基于证据表的模板回答，不凭空生成)
  - /api/report/{id}       风险分析报告 (Markdown / HTML / 可下载 .md)
  - /api/search            简单关键词检索 (RAG 召回)

设计原则：所有 AI 回答都"基于证据表"，可追溯到具体数据来源，避免凭空捏造。
"""
import os
import sys
import json
import re
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse, Response, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)   # 兼容 uvicorn backend.app:app 启动
import nlu  # 自然语言理解与对话引擎（同包模块）
import report_gen  # 报告生成引擎（Word/Markdown/HTML）
DATA = os.path.join(HERE, "data")
FRONTEND = os.path.join(os.path.dirname(HERE), "frontend")

# ----------------------------------------------------------------------------
# 加载数据
# ----------------------------------------------------------------------------
def _load(*path):
    with open(os.path.join(DATA, *path), "r", encoding="utf-8") as f:
        return json.load(f)

MANIFEST = _load("manifest.json")
RISK_BY_ID = {r["id"]: r for r in MANIFEST["risk_objects"]}
BOREHOLES = _load("boreholes", "boreholes.json")
BH_BY_ID = {b["id"]: b for b in BOREHOLES}
GEO_LINES = _load("geophysics", "lines.json")
GEO_BY_ID = {g["id"]: g for g in GEO_LINES}
REPORT = _load("report", "survey_report.json")

# ----------------------------------------------------------------------------
# FastAPI
# ----------------------------------------------------------------------------
app = FastAPI(title="多源勘察数据联动展示与证据链追溯系统", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# 静态：前端页面
app.mount("/ui", StaticFiles(directory=FRONTEND, html=True), name="ui")
# 静态：前端自有资源 (app.js/app.css/marked.min.js)
app.mount("/static", StaticFiles(directory=os.path.join(FRONTEND, "static")), name="static")
# 静态：前端三方库 (three/leaflet/echarts)
app.mount("/lib", StaticFiles(directory=os.path.join(FRONTEND, "static", "lib")), name="lib")
# 静态：数据文件 (图片/点云/csv)
app.mount("/data", StaticFiles(directory=DATA), name="data")


@app.get("/")
def index():
    """根路径直接返回前端首页。"""
    return FileResponse(os.path.join(FRONTEND, "index.html"))


# ----------------------------------------------------------------------------
# 1) 总览
# ----------------------------------------------------------------------------
@app.get("/api/manifest")
def get_manifest():
    """返回项目元信息、线路、数据源清单、风险对象摘要。"""
    risks = []
    for r in MANIFEST["risk_objects"]:
        risks.append({
            "id": r["id"], "name": r["name"], "mileage": r["mileage"],
            "type": r["type"], "type_cn": r["type_cn"],
            "risk_level": r["risk_level"], "confidence": r["confidence"],
            "center_xy": r["center_xy"], "polygon_xy": r["polygon_xy"],
            "borehole_ids": r.get("borehole_ids", []),
            "geophysics_line": r.get("geophysics_line"),
        })
    return {
        "project": MANIFEST["project"],
        "route": MANIFEST["route"],
        "data_sources": MANIFEST["data_sources"],
        "dem": MANIFEST["dem"], "orthophoto": MANIFEST["orthophoto"],
        "pointcloud": MANIFEST["pointcloud"],
        "risks": risks,
        "stats": {
            "risk_count": len(risks),
            "borehole_count": len(BOREHOLES),
            "geophysics_lines": len(GEO_LINES),
            "report_sections": len(REPORT["sections"]),
        }
    }


# ----------------------------------------------------------------------------
# 2) 风险对象详情 (多源证据)
# ----------------------------------------------------------------------------
@app.get("/api/risk/{rid}")
def get_risk(rid: str):
    r = RISK_BY_ID.get(rid)
    if not r:
        raise HTTPException(404, f"风险对象 {rid} 不存在")
    # 关联钻孔与物探
    bhs = [BH_BY_ID[bid] for bid in r.get("borehole_ids", []) if bid in BH_BY_ID]
    geo = GEO_BY_ID.get(r.get("geophysics_line"))
    # 关联报告段落
    related_sections = [s for s in REPORT["sections"] if rid in s.get("related_risks", [])]
    return {
        "risk": r,
        "boreholes": bhs,
        "geophysics": geo,
        "report_sections": related_sections,
        # 给前端的证据卡片清单 (顺序固定：影像→点云→物探→钻孔→文本)
        "evidence_cards": [
            {"source": "正射影像", "icon": "image", "content": r["evidence"]["image"],
             "file": MANIFEST["orthophoto"]["image"], "kind": "image"},
            {"source": "三维点云", "icon": "mountain", "content": r["evidence"]["pointcloud"],
             "file": MANIFEST["pointcloud"]["file"], "kind": "pointcloud"},
            {"source": "物探剖面", "icon": "wave", "content": r["evidence"]["geophysics"],
             "file": geo["image"] if geo else None, "kind": "geophysics",
             "extra": geo},
            {"source": "钻孔资料", "icon": "drill", "content": r["evidence"]["borehole"],
             "file": [f"boreholes/{b['id']}.png" for b in bhs], "kind": "borehole",
             "extra": bhs},
            {"source": "勘察报告", "icon": "doc", "content": r["evidence"]["report"],
             "file": None, "kind": "text",
             "extra": related_sections},
        ]
    }


# ----------------------------------------------------------------------------
# 3) 钻孔 / 物探
# ----------------------------------------------------------------------------
@app.get("/api/boreholes")
def get_boreholes(bid: Optional[str] = None):
    if bid:
        b = BH_BY_ID.get(bid)
        if not b:
            raise HTTPException(404, f"钻孔 {bid} 不存在")
        return b
    return {"boreholes": BOREHOLES}


@app.get("/api/geophysics")
def get_geophysics(lid: Optional[str] = None):
    if lid:
        g = GEO_BY_ID.get(lid)
        if not g:
            raise HTTPException(404, f"物探测线 {lid} 不存在")
        return g
    return {"lines": GEO_LINES}


# ----------------------------------------------------------------------------
# 4) 关键词检索 (简易 RAG 召回)
# ----------------------------------------------------------------------------
@app.get("/api/search")
def search(q: str = Query(..., description="关键词")):
    q = q.strip()
    if not q:
        return {"results": []}
    results = []
    # 在风险对象、报告段落中匹配
    ql = q.lower()
    for r in MANIFEST["risk_objects"]:
        blob = json.dumps(r, ensure_ascii=False).lower()
        if ql in blob:
            results.append({"type": "risk", "id": r["id"], "title": r["name"],
                            "snippet": r["evidence"]["report"][:120]})
    for s in REPORT["sections"]:
        if ql in s["content"].lower() or ql in s["title"].lower():
            results.append({"type": "report", "id": s["id"], "title": s["title"],
                            "snippet": s["content"][:120]})
    return {"query": q, "count": len(results), "results": results}


# ----------------------------------------------------------------------------
# 5) 证据链问答
#    原则：不调用外部大模型，避免凭空生成；
#    通过关键词匹配风险对象 → 返回结构化证据 + 解释 + 设计建议。
# ----------------------------------------------------------------------------
QA_PROBES = [
    # (正则, 匹配的风险对象或动作)
    (r"K12\+?380|R001|洞口|边坡|边坡失稳|卸荷|滑坡", "R001"),
    (r"K12\+?720|R002|富水|破碎带|突水|突泥|地下水", "R002"),
    (r"K12\+?050|R003|松散|堆积|沉降|明洞|碎石土", "R003"),
    (r"(概览|总结|所有|全部|风险清单|有哪些)", "__ALL__"),
]


class QAReq(BaseModel):
    question: str


@app.post("/api/qa")
def qa(req: QAReq):
    q = req.question.strip()
    if not q:
        raise HTTPException(400, "问题不能为空")
    matched = []
    for pat, rid in QA_PROBES:
        if re.search(pat, q, flags=re.IGNORECASE):
            if rid == "__ALL__":
                matched = list(RISK_BY_ID.keys()); break
            if rid not in matched:
                matched.append(rid)
    # 若问题"是什么/怎么判断/解释"等且无里程匹配，回退总览
    if not matched and re.search(r"(风险|地质|建议|说明|情况|问题)", q):
        matched = list(RISK_BY_ID.keys())

    if not matched:
        return {
            "question": q,
            "answered": False,
            "answer": (
                "未在该工程样例中匹配到相关风险对象。本系统当前覆盖三个示范风险："
                "K12+380 洞口边坡失稳、K12+720 富水破碎带、K12+050 松散堆积区。"
                "您可以询问具体里程或风险类型，例如「K12+380 为什么是高风险」或「富水破碎带如何处理」。"
            ),
            "evidence_refs": [],
        }

    # 组装回答
    parts = []
    refs = []
    if matched == list(RISK_BY_ID.keys()) and len(matched) > 1:
        # 总览模式
        parts.append("本工程 K12+000 ~ K13+000 段共识别 **3 处** 主要风险，按里程梳理如下：\n")
        for rid in matched:
            r = RISK_BY_ID[rid]
            parts.append(f"• **{r['mileage']} {r['type_cn']}**（风险等级：{r['risk_level']}）— "
                         f"{r['evidence']['image']}；{r['evidence']['borehole']}。")
            refs.append({"risk_id": rid, "title": r["name"]})
        parts.append("\n建议按分段采取针对性工程措施，施工期建立监控量测体系。")
    else:
        for rid in matched:
            r = RISK_BY_ID[rid]
            parts.append(f"### {r['name']}（{r['mileage']}）\n")
            parts.append(f"**风险类型**：{r['type_cn']}　**风险等级**：{r['risk_level']}　**可信度**：{r['confidence']}\n")
            parts.append("**多源证据**：")
            parts.append(f"- 🛰 正射影像：{r['evidence']['image']}")
            parts.append(f"- 🏔 三维点云：{r['evidence']['pointcloud']}")
            parts.append(f"- 📡 物探剖面：{r['evidence']['geophysics']}")
            parts.append(f"- 🔩 钻孔资料：{r['evidence']['borehole']}")
            parts.append(f"- 📄 勘察报告：{r['evidence']['report']}\n")
            parts.append(f"**综合解释**：{r['interpretation']}\n")
            parts.append(f"**设计建议**：{r['design_suggestion']}\n")
            refs.append({"risk_id": rid, "title": r["name"]})

    return {
        "question": q,
        "answered": True,
        "answer": "\n".join(parts),
        "evidence_refs": refs,
        "matched_risks": matched,
    }


# ----------------------------------------------------------------------------
# 6.5) 智能对话接口 /api/chat
#      基于本地 NLU 引擎：意图识别 + RAG 检索 + 多轮对话 + 条件查询 + 动作触发
#      完全离线，无需外部大模型 API。
# ----------------------------------------------------------------------------
class ChatReq(BaseModel):
    message: str
    session_id: Optional[str] = "default"


@app.post("/api/chat")
def chat(req: ChatReq):
    msg = (req.message or "").strip()
    if not msg:
        raise HTTPException(400, "消息不能为空")
    result = nlu.generate_response(msg, sid=req.session_id or "default")
    return {
        "session_id": result["session_id"],
        "intent": result["intent"],
        "answer": result["answer"],
        "actions": result["actions"],            # 前端据此执行 locate/gen_report 等
        "evidence_refs": result["evidence_refs"],
        "matched_risk": result.get("matched_risk"),
    }


@app.get("/api/chat/suggest")
def chat_suggest():
    """推荐问题示例（供前端快捷输入）。"""
    return {"suggestions": [
        {"q": "带我去看看 K12+380 的边坡", "type": "locate", "icon": "🗺️"},
        {"q": "坡度大于 30 度的风险有哪些", "type": "query", "icon": "🔍"},
        {"q": "地下水位浅于 3 米的钻孔", "type": "query", "icon": "💧"},
        {"q": "R001 和 R002 哪个风险更高", "type": "compare", "icon": "📊"},
        {"q": "K12+720 富水破碎带如何处理", "type": "explain", "icon": "💡"},
        {"q": "给 R001 生成一份报告", "type": "report", "icon": "📑"},
        {"q": "K12+300 到 K12+800 之间有什么风险", "type": "query", "icon": "📏"},
        {"q": "全线有哪些风险，给个总结", "type": "query", "icon": "📋"},
    ]}


# ----------------------------------------------------------------------------
# 7) 报告生成引擎 (Word .docx / Markdown / HTML，单风险 + 全线综合)
#    由 report_gen.py 驱动，支持多格式、嵌入物探剖面与钻孔柱状图。
# ----------------------------------------------------------------------------
@app.get("/api/report")
def report_overview():
    """报告能力总览：列出可生成的报告与格式。"""
    risks = [{"id": r["id"], "name": r["name"], "mileage": r["mileage"],
              "type_cn": r["type_cn"], "level": r["risk_level"]} for r in MANIFEST["risk_objects"]]
    return {
        "formats": [
            {"id": "docx", "name": "Word 文档", "ext": ".docx",
             "desc": "正式工程交付文档，含封面/表格/嵌入图"},
            {"id": "md", "name": "Markdown", "ext": ".md",
             "desc": "轻量纯文本，可版本控制"},
            {"id": "html", "name": "HTML 网页", "ext": ".html",
             "desc": "浏览器直接打开，可打印为 PDF"},
        ],
        "scopes": [
            {"id": "full", "name": "全线综合报告",
             "desc": "工程概述 + 风险统计 + 逐风险分析 + 对比 + 总体结论"},
            {"id": "risk", "name": "单风险报告", "desc": "聚焦单个风险的多源证据与建议"},
        ],
        "risks": risks,
    }


@app.get("/api/report/preview")
def report_preview(scope: str = "full", rid: Optional[str] = None):
    """报告在线预览（返回 Markdown + HTML body，不下载文件）。"""
    try:
        return report_gen.preview_report(scope=scope, rid=rid)
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.get("/api/report/download")
def report_download(scope: str = "full", rid: Optional[str] = None, fmt: str = "docx"):
    """报告下载（返回文件流）。中文文件名用 RFC 5987 编码，兼容各浏览器。"""
    try:
        r = report_gen.generate_report(scope=scope, rid=rid, fmt=fmt)
    except ValueError as e:
        raise HTTPException(400, str(e))
    from urllib.parse import quote
    fname = r["filename"]
    # RFC 5987: filename* 用 UTF-8 百分号编码；同时给 ASCII filename 兜底
    ascii_fallback = "report." + fmt
    disposition = f"attachment; filename=\"{ascii_fallback}\"; filename*=UTF-8''{quote(fname)}"
    return Response(
        content=r["content"],
        media_type=r["media_type"],
        headers={"Content-Disposition": disposition}
    )


# 兼容旧接口：/api/report/{rid}  (单风险 Markdown 预览)
@app.get("/api/report/{rid}")
def gen_report_legacy(rid: str, download: int = 0):
    if rid not in RISK_BY_ID:
        raise HTTPException(404, f"风险对象 {rid} 不存在")
    if download:
        return report_download(scope="risk", rid=rid, fmt="md")
    return report_gen.preview_report(scope="risk", rid=rid)


# ----------------------------------------------------------------------------
# 8) 健康检查
# ----------------------------------------------------------------------------
@app.get("/api/health")
def health():
    return {"status": "ok", "data_root": DATA,
            "risk_count": len(RISK_BY_ID), "borehole_count": len(BH_BY_ID),
            "report_formats": ["docx", "md", "html"]}


# ----------------------------------------------------------------------------
# 9) 风险多维评分 (供 ECharts 雷达图)
#    把每个风险量化为 6 个维度（0-100 分，越高越危险）：
#    地形坡度 / 高差起伏 / 物探异常 / 钻孔揭露 / 地下水 / 报告描述
# ----------------------------------------------------------------------------
def _score_risk(r):
    """根据风险参数 + 证据，计算各维度评分 (0-100)。"""
    p = r["evidence"].get("params", {})
    # 地形坡度：最大坡度归一化到 0-100（45°=满分）
    slope = p.get("max_slope_deg", p.get("avg_slope_deg", 15))
    slope_score = min(100, round(slope / 45 * 100))
    # 高差起伏：相对高差归一化（60m=满分）
    relief = p.get("relief_m", 10)
    relief_score = min(100, round(relief / 60 * 100))
    # 物探异常：电阻率越低越危险（100Ω·m=满分，1000Ω·m=0）
    rho = p.get("rho_min", 1000)
    geo_score = max(0, min(100, round((1000 - rho) / 900 * 100)))
    # 钻孔揭露：风化层/破碎带厚度归一化（15m=满分）
    weathered = p.get("weathered_depth_m", p.get("deposit_depth_m", 5))
    rqd = p.get("rqd_pct", 80)
    bh_score = min(100, round(weathered / 15 * 70 + (100 - rqd) / 100 * 30))
    # 地下水：水位埋深越浅越危险（0m=满分，10m=0）；无水位数据给中等
    wd = p.get("water_depth_m")
    water_score = max(20, min(100, round((10 - wd) / 10 * 100))) if wd is not None else 40
    # 综合等级分：高=90, 中高=70, 中=50
    level_score = {"高": 90, "中高": 70, "中": 50}.get(r["risk_level"], 50)
    return {
        "slope": slope_score, "relief": relief_score, "geophysics": geo_score,
        "borehole": bh_score, "groundwater": water_score, "level": level_score,
    }


@app.get("/api/risk_scores")
def risk_scores(rid: Optional[str] = None):
    """返回风险多维评分，供前端 ECharts 雷达图。
    不指定 rid 时返回全部风险（用于对比）。"""
    dims = [
        {"name": "地形坡度", "max": 100},
        {"name": "高差起伏", "max": 100},
        {"name": "物探异常", "max": 100},
        {"name": "钻孔揭露", "max": 100},
        {"name": "地下水", "max": 100},
        {"name": "综合等级", "max": 100},
    ]
    if rid:
        r = RISK_BY_ID.get(rid)
        if not r:
            raise HTTPException(404, f"风险 {rid} 不存在")
        s = _score_risk(r)
        return {"dimensions": dims, "risk": {
            "id": rid, "name": r["name"], "mileage": r["mileage"],
            "level": r["risk_level"],
            "values": [s["slope"], s["relief"], s["geophysics"],
                       s["borehole"], s["groundwater"], s["level"]],
            "scores": s,
        }}
    series = []
    for r in sorted(MANIFEST["risk_objects"], key=lambda x: x["mileage_m"]):
        s = _score_risk(r)
        series.append({
            "id": r["id"], "name": r["mileage"] + " " + r["type_cn"],
            "level": r["risk_level"],
            "values": [s["slope"], s["relief"], s["geophysics"],
                       s["borehole"], s["groundwater"], s["level"]],
        })
    return {"dimensions": dims, "risks": series}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)
