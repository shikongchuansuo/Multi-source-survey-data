# -*- coding: utf-8 -*-
"""对话业务。

对应原 ``app.py`` 的：
- ``/api/qa``        —— 证据链问答（正则模板回答）
- ``/api/chat``      —— NLU 意图识别 + RAG + 多轮对话（调 engines/nlu）
- ``/api/chat/suggest`` —— 推荐问题示例

逻辑原样迁移，保证回答文本、字段名完全一致。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

from app.core.exceptions import ValidationError
from app.engines import nlu_engine
from app.repositories import get_risk_repo

# 风险匹配探针（与原 app.py::QA_PROBES 一致）
_QA_PROBES: List[Tuple[str, str]] = [
    (r"K12\+?380|R001|洞口|边坡|边坡失稳|卸荷|滑坡", "R001"),
    (r"K12\+?720|R002|富水|破碎带|突水|突泥|地下水", "R002"),
    (r"K12\+?050|R003|松散|堆积|沉降|明洞|碎石土", "R003"),
    (r"(概览|总结|所有|全部|风险清单|有哪些)", "__ALL__"),
]

# 推荐问题（与原 app.py::chat_suggest 一致）
_SUGGESTIONS = [
    {"q": "带我去看看 K12+380 的边坡", "type": "locate", "icon": "🗺️"},
    {"q": "坡度大于 30 度的风险有哪些", "type": "query", "icon": "🔍"},
    {"q": "地下水位浅于 3 米的钻孔", "type": "query", "icon": "💧"},
    {"q": "R001 和 R002 哪个风险更高", "type": "compare", "icon": "📊"},
    {"q": "K12+720 富水破碎带如何处理", "type": "explain", "icon": "💡"},
    {"q": "给 R001 生成一份报告", "type": "report", "icon": "📑"},
    {"q": "K12+300 到 K12+800 之间有什么风险", "type": "query", "icon": "📏"},
    {"q": "全线有哪些风险，给个总结", "type": "query", "icon": "📋"},
]


class ChatService:
    def __init__(self) -> None:
        self.risk_repo = get_risk_repo()

    # ---- /api/qa ----
    def qa(self, question: str) -> Dict[str, Any]:
        q = question.strip()
        if not q:
            raise ValidationError("问题不能为空")

        risk_map = self.risk_repo.risk_map()
        risk_ids = list(risk_map.keys())
        matched: List[str] = []
        for pat, rid in _QA_PROBES:
            if re.search(pat, q, flags=re.IGNORECASE):
                if rid == "__ALL__":
                    matched = list(risk_ids)
                    break
                if rid not in matched:
                    matched.append(rid)
        # 回退总览
        if not matched and re.search(r"(风险|地质|建议|说明|情况|问题)", q):
            matched = list(risk_ids)

        if not matched:
            return {
                "question": q,
                "answered": False,
                "answer": (
                    "未在该工程样例中匹配到相关风险对象。本系统当前覆盖三个示范风险："
                    "K12+380 洞口边坡失稳、K12+720 富水破碎带、K12+050 松散堆积区。"
                    "您可以询问具体里程或风险类型，例如「K12+380 为什么是高风险」"
                    "或「富水破碎带如何处理」。"
                ),
                "evidence_refs": [],
            }

        parts: List[str] = []
        refs: List[Dict[str, Any]] = []
        if matched == list(risk_map.keys()) and len(matched) > 1:
            parts.append("本工程 K12+000 ~ K13+000 段共识别 **3 处** 主要风险，按里程梳理如下：\n")
            for rid in matched:
                r = risk_map[rid]
                parts.append(f"• **{r['mileage']} {r['type_cn']}**（风险等级：{r['risk_level']}）— "
                             f"{r['evidence']['image']}；{r['evidence']['borehole']}。")
                refs.append({"risk_id": rid, "title": r["name"]})
            parts.append("\n建议按分段采取针对性工程措施，施工期建立监控量测体系。")
        else:
            for rid in matched:
                r = risk_map[rid]
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

    # ---- /api/chat ----
    def chat(self, message: str, session_id: str | None = "default") -> Dict[str, Any]:
        msg = (message or "").strip()
        if not msg:
            raise ValidationError("消息不能为空")
        result = nlu_engine.generate_response(msg, sid=session_id or "default")
        return {
            "session_id": result["session_id"],
            "intent": result["intent"],
            "answer": result["answer"],
            "actions": result["actions"],
            "evidence_refs": result["evidence_refs"],
            "matched_risk": result.get("matched_risk"),
        }

    # ---- /api/chat/suggest ----
    def suggestions(self) -> Dict[str, Any]:
        return {"suggestions": list(_SUGGESTIONS)}
