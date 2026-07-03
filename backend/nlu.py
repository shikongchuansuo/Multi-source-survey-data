# -*- coding: utf-8 -*-
"""
自然语言理解与对话引擎 (NLU Engine)
====================================
完全离线运行，无需外部 API / 大模型，保证比赛现场断网可用。

提供四个核心能力：
  1) RAG 检索 —— 把报告/风险/钻孔文本切成语料，TF-IDF 向量化，召回相关片段
  2) 意图识别 —— 把用户问题归类为 locate(定位) / query(条件查询) /
                  compare(对比) / explain(解释) / report(报告) / greet(问候)
  3) 参数抽取 —— 从问题里抽出风险 ID、里程、阈值（坡度>X、水位<Y）等
  4) 对话状态 —— 维护最近提到的风险对象，支持指代消解（"它"/"这个"指代）

设计原则：规则 + 检索混合。工程上可解释、可追溯，回答都带证据来源。
"""
import re
import json
import os
from typing import Optional, List, Dict, Any, Tuple

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data")

# ----------------------------------------------------------------------------
# 加载语料
# ----------------------------------------------------------------------------
def _load(*path):
    with open(os.path.join(DATA, *path), "r", encoding="utf-8") as f:
        return json.load(f)

MANIFEST = _load("manifest.json")
RISKS = MANIFEST["risk_objects"]
RISK_BY_ID = {r["id"]: r for r in RISKS}
BOREHOLES = _load("boreholes", "boreholes.json")
BH_BY_ID = {b["id"]: b for b in BOREHOLES}
GEO_LINES = _load("geophysics", "lines.json")
REPORT = _load("report", "survey_report.json")

# ----------------------------------------------------------------------------
# 1) RAG 语料库构建：把所有可检索文本切成"语料片段"，每段带来源标签
# ----------------------------------------------------------------------------
def build_corpus() -> List[Dict[str, Any]]:
    """构建检索语料：每个片段 = {id, text, source, source_id}"""
    docs = []
    # 1.1 风险对象的全部证据文本
    for r in RISKS:
        rid = r["id"]
        docs.append({"id": f"{rid}_name", "text": r["name"], "source": "risk", "source_id": rid})
        docs.append({"id": f"{rid}_interp", "text": r["interpretation"],
                     "source": "risk_interp", "source_id": rid})
        docs.append({"id": f"{rid}_suggest", "text": r["design_suggestion"],
                     "source": "risk_suggest", "source_id": rid})
        for k, v in r["evidence"].items():
            if isinstance(v, str):
                docs.append({"id": f"{rid}_{k}", "text": v, "source": "risk_ev", "source_id": rid})
    # 1.2 钻孔
    for b in BOREHOLES:
        txt = f"{b['id']} 钻孔 里程 {b['mileage']} 孔深 {b['depth_m']}m 高程 {b['elevation']}m "
        if b["water_depth_m"] is not None:
            txt += f"地下水位埋深 {b['water_depth_m']}m "
        for L in b["layers"]:
            txt += f"{L['top']}-{L['bottom']}m {L['lithology']} {L['desc']} "
        docs.append({"id": b["id"], "text": txt, "source": "borehole", "source_id": b["id"]})
    # 1.3 物探
    for g in GEO_LINES:
        docs.append({"id": g["id"], "text": f"{g['name']} {g['method']} 长度{g['length_m']}m 最低电阻率{g['rho_min']}Ω·m 异常深度{g['anomaly_depth_m']}m",
                     "source": "geophysics", "source_id": g["id"]})
    # 1.4 报告段落
    for s in REPORT["sections"]:
        docs.append({"id": s["id"], "text": s["title"] + " " + s["content"],
                     "source": "report", "source_id": s["id"]})
    return docs


CORPUS = build_corpus()
CORPUS_TEXTS = [d["text"] for d in CORPUS]
# 字符级 1-2 gram，对中文友好（无需分词器）
_VECTORIZER = TfidfVectorizer(analyzer="char_wb", ngram_range=(1, 2), min_df=1)
_CORPUS_MATRIX = _VECTORIZER.fit_transform(CORPUS_TEXTS)


def rag_retrieve(query: str, topk: int = 5) -> List[Dict[str, Any]]:
    """对 query 做检索，返回 topk 相关语料片段（带相似度）。"""
    qv = _VECTORIZER.transform([query])
    sims = cosine_similarity(qv, _CORPUS_MATRIX)[0]
    order = np.argsort(sims)[::-1][:topk]
    out = []
    for i in order:
        if sims[i] <= 0:
            continue
        d = CORPUS[i].copy()
        d["score"] = round(float(sims[i]), 3)
        out.append(d)
    return out


# ----------------------------------------------------------------------------
# 2) 意图识别
# ----------------------------------------------------------------------------
INTENT_PATTERNS = [
    ("greet",     r"^(你好|您好|hi|hello|嗨|在吗|你是谁|能做什么|帮助|功能)"),
    ("report",    r"(生成|写|出|做).*(报告|说明|文档|分析)"),
    ("compare",   r"(对比|比较|区别|哪个.*高|哪个.*大|哪个.*严重|vs|VS|和.*比)"),
    # 纯条件查询优先级最高（避免被 explain 的关键词抢走）
    ("query",     r"(坡度.*(大于|超过|>|≥|高于)|水位.*(小于|低于|浅|<|≤)|电阻率.*(小于|低于|<|大于|超过)|RQD|有哪些|列出|统计|全部.*风险)"),
    ("query",     r"K12\+?\d{3}.*(之间|到|至|范围|~)"),     # 里程范围查询
    ("query",     r"(哪些|多少|几个).*(钻孔|风险|边坡|物探|地层)"),
    ("locate",    r"(带我去|去看看|定位|跳转|打开|显示一下|看看|查看|去看).*(风险|边坡|破碎带|堆积|K12|R00)"),
    ("locate",    r"(定位|查看|打开).*(K12\+?\d+|R00\d|富水|边坡|破碎|堆积|洞口|钻孔|物探)"),
    ("explain",   r"(为什么|原因|解释|说明一下|怎么回事|什么情况|怎么办|如何处理|怎么处理|建议|措施|支护|治理|截排水|排水)"),
    ("explain",   r"(K12\+?\d+|R00\d|富水|边坡|破碎|堆积|洞口|突水|滑坡|沉降)"),
]


def detect_intent(text: str) -> str:
    """识别意图，返回 intent 名。"""
    for intent, pat in INTENT_PATTERNS:
        if re.search(pat, text, flags=re.IGNORECASE):
            return intent
    return "explain"  # 默认走解释/检索


# ----------------------------------------------------------------------------
# 3) 参数抽取
# ----------------------------------------------------------------------------
def extract_risk_id(text: str, context_rid: Optional[str] = None,
                     intent: Optional[str] = None) -> Optional[str]:
    """从文本抽风险 ID，支持指代消解。
    intent='query' 且含阈值条件时不做关键词匹配（避免误命中）。"""
    # 直接 R00x
    m = re.search(r"R00([123])", text, flags=re.IGNORECASE)
    if m:
        return "R00" + m.group(1)
    # 里程 K12+xxx → 匹配最近的风险
    m = re.search(r"K12\+?(\d{3})", text, flags=re.IGNORECASE)
    if m:
        mile = 12000 + int(m.group(1))
        best, best_d = None, 1e9
        for r in RISKS:
            d = abs(r["mileage_m"] - mile)
            if d < best_d:
                best_d, best = d, r["id"]
        if best_d < 250:  # 250m 内算命中
            return best
    # 纯条件查询（坡度>X/水位<Y 等阈值）不做关键词匹配，避免误判
    if intent == "query" and (extract_thresholds(text) or extract_mileage_range(text)):
        return context_rid
    # 关键词匹配
    kw_map = [("边坡|卸荷|滑坡|洞口", "R001"),
              ("富水|破碎|突水|突泥", "R002"),
              ("松散|堆积|沉降|明洞|碎石土", "R003")]
    lowered = text.lower()
    for kws, rid in kw_map:
        if re.search(kws, lowered):
            return rid
    # 指代消解：含"它/这个/该/那个/此处/这里"
    if context_rid and re.search(r"(它|这个|该|那个|此处|这里|这一|这段)", text):
        return context_rid
    return context_rid  # 兜底返回上下文


def extract_thresholds(text: str) -> Dict[str, Optional[float]]:
    """抽阈值参数：坡度>X、水位<Y、电阻率<X 等。"""
    out = {"slope_gt": None, "slope_lt": None,
           "water_lt": None, "rho_lt": None, "rho_gt": None}
    # 坡度
    m = re.search(r"坡度[^\d]*(大于|超过|>|≥|高于|至少)\s*(\d+(\.\d+)?)", text)
    if m: out["slope_gt"] = float(m.group(2))
    m = re.search(r"坡度[^\d]*(小于|低于|<|≤|至多)\s*(\d+(\.\d+)?)", text)
    if m: out["slope_lt"] = float(m.group(2))
    # 地下水位埋深 < Y (浅于)
    m = re.search(r"(水位|地下水)[^\d]*(小于|低于|浅|<|≤|浅于)\s*(\d+(\.\d+)?)", text)
    if m: out["water_lt"] = float(m.group(3))
    # 电阻率
    m = re.search(r"(电阻率|低阻)[^\d]*(小于|低于|<|≤)\s*(\d+(\.\d+)?)", text)
    if m: out["rho_lt"] = float(m.group(3))
    m = re.search(r"(电阻率|高阻)[^\d]*(大于|超过|>|≥)\s*(\d+(\.\d+)?)", text)
    if m: out["rho_gt"] = float(m.group(3))
    return {k: v for k, v in out.items() if v is not None}


def extract_mileage_range(text: str) -> Optional[Tuple[float, float]]:
    """抽里程范围，如 K12+500 到 K12+800。"""
    nums = re.findall(r"K12\+?(\d{3})", text, flags=re.IGNORECASE)
    if len(nums) >= 2:
        a, b = sorted([12000 + int(nums[0]), 12000 + int(nums[1])])
        return (a, b)
    if len(nums) == 1:
        m = 12000 + int(nums[0])
        return (m - 100, m + 100)
    return None


# ----------------------------------------------------------------------------
# 4) 条件查询引擎
# ----------------------------------------------------------------------------
def query_risks_by_condition(th: Dict[str, float]) -> List[Dict]:
    """按阈值筛选风险对象。"""
    res = []
    for r in RISKS:
        p = r["evidence"].get("params", {})
        ok = True
        if "slope_gt" in th and p.get("max_slope_deg", p.get("avg_slope_deg", 0)) < th["slope_gt"]:
            ok = False
        if "slope_lt" in th and p.get("max_slope_deg", p.get("avg_slope_deg", 0)) > th["slope_lt"]:
            ok = False
        if "rho_lt" in th and p.get("rho_min", 9999) > th["rho_lt"]:
            ok = False
        if "rho_gt" in th and p.get("rho_min", 0) < th["rho_gt"]:
            ok = False
        if ok:
            res.append(r)
    return res


def query_boreholes_by_condition(th: Dict[str, float]) -> List[Dict]:
    """按阈值筛选钻孔。"""
    res = []
    for b in BOREHOLES:
        ok = True
        wd = b.get("water_depth_m")
        if "water_lt" in th:
            if wd is None or wd > th["water_lt"]:
                ok = False
        if ok:
            res.append(b)
    return res


def _bh_mileage_m(bh: Dict) -> float:
    """钻孔里程字符串 'K12+050' -> 12050。"""
    m = re.search(r"K12\+?(\d{3})", bh.get("mileage", ""))
    return 12000 + int(m.group(1)) if m else 0


def query_by_mileage(mrange: Tuple[float, float]) -> Dict[str, List]:
    """按里程范围查询风险/钻孔。"""
    a, b = mrange
    risks = [r for r in RISKS if a <= r["mileage_m"] <= b]
    bhs = [bh for bh in BOREHOLES if a <= _bh_mileage_m(bh) <= b]
    return {"risks": risks, "boreholes": bhs}


# ----------------------------------------------------------------------------
# 5) 对话状态（按会话 id 维护）
# ----------------------------------------------------------------------------
class DialogueState:
    def __init__(self):
        self.last_risk_id: Optional[str] = None  # 最近提到的风险（指代消解用）
        self.history: List[Dict] = []            # 多轮对话历史

    def update(self, user_text: str, rid: Optional[str]):
        if rid:
            self.last_risk_id = rid
        self.history.append({"role": "user", "text": user_text, "rid": rid})
        if len(self.history) > 20:
            self.history = self.history[-20:]


# 会话池（演示用，单进程内存）
SESSIONS: Dict[str, DialogueState] = {}


def get_session(sid: str) -> DialogueState:
    if sid not in SESSIONS:
        SESSIONS[sid] = DialogueState()
    return SESSIONS[sid]


# ----------------------------------------------------------------------------
# 6) 综合回答生成器（按意图分发）
# ----------------------------------------------------------------------------
def generate_response(text: str, sid: str = "default") -> Dict[str, Any]:
    """主入口：识别意图 → 处理 → 返回结构化回答。
    返回字段：
      intent: 意图
      answer: markdown 文本回答
      actions: 需要前端执行的动作 (locate_risk/switch_layer/gen_report/...)
      evidence_refs: 证据来源卡片
      session_id: 会话 id
    """
    state = get_session(sid)
    intent = detect_intent(text)
    rid = extract_risk_id(text, state.last_risk_id, intent=intent)
    actions: List[Dict] = []
    refs: List[Dict] = []

    # ---------- greet ----------
    if intent == "greet":
        ans = (
            "您好！我是**多源勘察数据联动展示与证据链追溯系统**的智能助手。\n\n"
            "我能帮您：\n"
            "- 🗺️ **定位风险**：「带我去看看 K12+380 的边坡」\n"
            "- 🔍 **条件查询**：「坡度大于 30 度的风险有哪些」「地下水位浅于 3 米的钻孔」\n"
            "- 📊 **对比分析**：「R001 和 R002 哪个风险更高」\n"
            "- 💡 **风险解释**：「K12+720 富水破碎带如何处理」\n"
            "- 📑 **生成报告**：「给 R001 生成一份报告」\n\n"
            "当前案例区有 3 个风险：K12+380 边坡失稳(高)、K12+720 富水破碎带(中高)、K12+050 松散堆积(中)。"
        )

    # ---------- locate ----------
    elif intent == "locate":
        if rid:
            r = RISK_BY_ID[rid]
            actions.append({"type": "locate_risk", "risk_id": rid})
            ans = (f"已为您定位到 **{r['name']}**（{r['mileage']}）。\n\n"
                   f"- 风险类型：{r['type_cn']}\n- 风险等级：**{r['risk_level']}**\n\n"
                   f"右侧证据链已联动更新，3D 视图已飞行到该区域。"
                   f"{' 关联钻孔：' + '、'.join(r.get('borehole_ids', [])) + '。' if r.get('borehole_ids') else ''}")
            refs.append({"risk_id": rid, "title": r["name"]})
        else:
            # 定位钻孔/物探
            bh = re.search(r"钻孔\s*(ZK\d)", text, flags=re.IGNORECASE)
            if bh:
                actions.append({"type": "locate_borehole", "borehole_id": bh.group(1).upper()})
                ans = f"已为您定位到钻孔 **{bh.group(1).upper()}**。"
            else:
                ans = "请问您想查看哪个风险区或钻孔？例如「带我去看看 K12+380 的边坡」或「定位 ZK3」。"

    # ---------- report ----------
    elif intent == "report":
        if rid:
            actions.append({"type": "gen_report", "risk_id": rid})
            r = RISK_BY_ID[rid]
            ans = (f"已为您生成 **{r['name']}** 的风险分析报告。\n\n"
                   "请查看下方「报告生成」标签页，报告包含基本信息、多源证据表、"
                   "关键参数、综合解释与设计建议、钻孔地层表。可下载 .md 文件。")
            refs.append({"risk_id": rid, "title": r["name"]})
        else:
            ans = "请问要为哪个风险生成报告？例如「给 R001 生成报告」或「K12+380 出一份分析」。"

    # ---------- compare ----------
    elif intent == "compare":
        ids = re.findall(r"R00([123])", text, flags=re.IGNORECASE)
        ids = ["R00" + i for i in ids]
        if len(ids) < 2:
            # 尝试用关键词补全
            kw = re.findall(r"(边坡|富水|堆积)", text)
            kwmap = {"边坡": "R001", "富水": "R002", "堆积": "R003"}
            for k in kw:
                kid = kwmap.get(k)
                if kid and kid not in ids:
                    ids.append(kid)
        if len(ids) >= 2:
            ans, cmp_refs = _compare_risks(ids[:2])
            refs.extend(cmp_refs)
            actions.append({"type": "locate_risk", "risk_id": ids[0]})
        else:
            ans = "请指定要对比的两个风险，例如「R001 和 R002 哪个风险更高」。"

    # ---------- query ----------
    elif intent == "query":
        th = extract_thresholds(text)
        mr = extract_mileage_range(text)
        ans_parts = []
        if th:
            risk_conds = {k: v for k, v in th.items()
                          if k in ("slope_gt", "slope_lt", "rho_lt", "rho_gt")}
            water_conds = {k: v for k, v in th.items() if k == "water_lt"}
            rq = query_risks_by_condition(risk_conds) if risk_conds else []
            bq = query_boreholes_by_condition(water_conds) if water_conds else []
            cond_str = "、".join(f"{k}={v}" for k, v in th.items())
            ans_parts.append(f"**条件筛选结果**（{cond_str}）：")
            if risk_conds:
                if rq:
                    ans_parts.append("- 符合条件的风险：" + "、".join(
                        f"{r['mileage']} {r['type_cn']}({r['risk_level']})" for r in rq))
                    for r in rq:
                        refs.append({"risk_id": r["id"], "title": r["name"]})
                else:
                    ans_parts.append("- 无符合该条件的风险")
            if water_conds:
                if bq:
                    ans_parts.append("- 符合条件的钻孔：" + "、".join(
                        f"{b['id']}(水位{b['water_depth_m']}m)" for b in bq))
                else:
                    ans_parts.append("- 无符合该条件的钻孔")
        if mr:
            q = query_by_mileage(mr)
            ans_parts.append(f"**里程范围 K12+{int(mr[0]-12000):03d} ~ K12+{int(mr[1]-12000):03d}**：")
            ans_parts.append("- 风险：" + ("、".join(f"{r['mileage']} {r['type_cn']}" for r in q["risks"]) or "无"))
            ans_parts.append("- 钻孔：" + ("、".join(b["id"] for b in q["boreholes"]) or "无"))
        if not th and not mr:
            # 通用统计
            ans_parts.append(_general_stats())
        ans = "\n".join(ans_parts) if ans_parts else "未识别到查询条件。可问「坡度大于 30 度的风险」「水位浅于 3 米的钻孔」「K12+300 到 K12+800 的风险」。"
        # 查询意图只在确实命中具体风险时才触发定位（避免条件查询误定位到上下文风险）
        if rid and RISK_BY_ID.get(rid) and refs:
            actions.append({"type": "locate_risk", "risk_id": rid})

    # ---------- explain (默认，走 RAG) ----------
    else:
        docs = rag_retrieve(text, topk=4)
        ans, refs = _build_rag_answer(text, rid, docs)
        if rid:
            actions.append({"type": "locate_risk", "risk_id": rid})

    # 更新会话状态
    state.update(text, rid)
    return {"intent": intent, "answer": ans, "actions": actions,
            "evidence_refs": refs, "session_id": sid, "matched_risk": rid}


# ----------------------------------------------------------------------------
# 辅助：对比 / RAG 回答 / 通用统计
# ----------------------------------------------------------------------------
def _compare_risks(ids: List[str]) -> Tuple[str, List[Dict]]:
    r1, r2 = RISK_BY_ID[ids[0]], RISK_BY_ID[ids[1]]
    level_rank = {"高": 3, "中高": 2, "中": 1}
    higher = r1 if level_rank[r1["risk_level"]] >= level_rank[r2["risk_level"]] else r2
    lines = [f"### 风险对比：{r1['mileage']} vs {r2['mileage']}", ""]
    lines.append("| 对比项 | {} | {} |".format(r1["mileage"], r2["mileage"]))
    lines.append("|---|---|---|")
    p1, p2 = r1["evidence"]["params"], r2["evidence"]["params"]
    lines.append(f"| 风险类型 | {r1['type_cn']} | {r2['type_cn']} |")
    lines.append(f"| 风险等级 | **{r1['risk_level']}** | **{r2['risk_level']}** |")
    lines.append(f"| 最大坡度(°) | {p1.get('max_slope_deg', p1.get('avg_slope_deg','—'))} | {p2.get('max_slope_deg', p2.get('avg_slope_deg','—'))} |")
    lines.append(f"| 最低电阻率(Ω·m) | {p1.get('rho_min','—')} | {p2.get('rho_min','—')} |")
    lines.append(f"| 关联钻孔 | {','.join(r1.get('borehole_ids',[])) or '—'} | {','.join(r2.get('borehole_ids',[])) or '—'} |")
    lines.append("")
    lines.append(f"**结论**：{higher['mileage']} {higher['type_cn']} 风险更高（{higher['risk_level']}）。"
                 f"主要差异：{higher['evidence']['pointcloud']}。")
    refs = [{"risk_id": r1["id"], "title": r1["name"]},
            {"risk_id": r2["id"], "title": r2["name"]}]
    return "\n".join(lines), refs


def _build_rag_answer(query: str, rid: Optional[str], docs: List[Dict]) -> Tuple[str, List[Dict]]:
    """基于检索片段 + 风险对象模板，拼出可追溯的回答。"""
    refs = []
    parts = []
    # 若匹配到具体风险，先给结构化解释
    if rid and RISK_BY_ID.get(rid):
        r = RISK_BY_ID[rid]
        parts.append(f"### {r['name']}（{r['mileage']}）")
        parts.append(f"**风险等级：{r['risk_level']}**　**类型：{r['type_cn']}**")
        parts.append("")
        parts.append(f"**综合解释**：{r['interpretation']}")
        parts.append("")
        parts.append(f"**设计建议**：{r['design_suggestion']}")
        refs.append({"risk_id": rid, "title": r["name"]})
        return "\n".join(parts), refs
    # 否则用检索片段
    used = [d for d in docs if d["score"] > 0.05][:3]
    if used:
        parts.append("根据勘察资料检索，相关信息如下：\n")
        for d in used:
            parts.append(f"- 【{_source_label(d['source'])}】{d['text'][:160]}{'…' if len(d['text'])>160 else ''}")
            if d["source"].startswith("risk"):
                refs.append({"risk_id": d["source_id"], "title": RISK_BY_ID.get(d["source_id"], {}).get("name", d["source_id"])})
            elif d["source"] == "borehole":
                refs.append({"risk_id": None, "title": "钻孔 " + d["source_id"], "borehole_id": d["source_id"]})
        return "\n".join(parts), refs
    return ("抱歉，在当前样例资料中未检索到高度相关的内容。"
            "可尝试询问具体里程或风险类型，例如「K12+380 边坡为什么是高风险」。"), []


def _source_label(s: str) -> str:
    return {"risk": "风险描述", "risk_interp": "风险解释", "risk_suggest": "设计建议",
            "risk_ev": "多源证据", "borehole": "钻孔资料", "geophysics": "物探剖面",
            "report": "勘察报告"}.get(s, s)


def _general_stats() -> str:
    high = [r for r in RISKS if r["risk_level"] == "高"]
    water = [b for b in BOREHOLES if b["water_depth_m"] is not None and b["water_depth_m"] < 5]
    return (f"**全线统计**（K12+000~K13+000）：\n"
            f"- 风险对象：{len(RISKS)} 个（高风险 {len(high)} 个）\n"
            f"- 钻孔：{len(BOREHOLES)} 个，其中浅层地下水(<5m) {len(water)} 个\n"
            f"- 物探测线：{len(GEO_LINES)} 条")


# ----------------------------------------------------------------------------
# 自测
# ----------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [
        "你好",
        "带我去看看 K12+380 的边坡",
        "坡度大于 30 度的风险有哪些",
        "地下水位浅于 3 米的钻孔",
        "R001 和 R002 哪个风险更高",
        "K12+720 富水破碎带如何处理",
        "给 R001 生成一份报告",
        "那它的截排水怎么设计",   # 指代 R001
        "K12+300 到 K12+800 之间有什么风险",
    ]
    print("=" * 60)
    print("NLU 引擎自测")
    print("=" * 60)
    for t in tests:
        r = generate_response(t, sid="test")
        print(f"\n▶ {t}")
        print(f"  意图={r['intent']} | 匹配风险={r['matched_risk']} | 动作={[a['type'] for a in r['actions']]}")
        print(f"  回答预览: {r['answer'][:80]}...")
