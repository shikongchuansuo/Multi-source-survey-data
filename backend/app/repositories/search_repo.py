# -*- coding: utf-8 -*-
"""检索 repository。

供 ``/api/search`` 关键词检索使用。当前实现：在风险对象 / 报告段落中
做子串匹配（与重构前 ``app.py`` 的 ``search`` 行为一致）。

未来（设计文档 Step 4）可替换为 PG 全文检索（``tsvector`` + ``ts_query``）。
"""
from __future__ import annotations

import json
from typing import Any, Dict, List

from app.repositories.file_repos import RiskFileRepo, ReportFileRepo


class SearchRepo:
    """关键词检索（文件模式实现）。"""

    def __init__(self,
                 risk_repo: RiskFileRepo | None = None,
                 report_repo: ReportFileRepo | None = None) -> None:
        self.risk_repo = risk_repo or RiskFileRepo()
        self.report_repo = report_repo or ReportFileRepo()

    def search(self, q: str) -> Dict[str, Any]:
        q = q.strip()
        if not q:
            return {"results": []}
        ql = q.lower()
        results: List[Dict[str, Any]] = []
        for r in self.risk_repo.all_risks():
            blob = json.dumps(r, ensure_ascii=False).lower()
            if ql in blob:
                results.append({
                    "type": "risk", "id": r["id"], "title": r["name"],
                    "snippet": r["evidence"]["report"][:120],
                })
        for s in self.report_repo.sections():
            if ql in s["content"].lower() or ql in s["title"].lower():
                results.append({
                    "type": "report", "id": s["id"], "title": s["title"],
                    "snippet": s["content"][:120],
                })
        return {"query": q, "count": len(results), "results": results}
