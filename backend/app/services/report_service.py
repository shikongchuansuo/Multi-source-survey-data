# -*- coding: utf-8 -*-
"""报告业务。

对应原 ``app.py`` 的 ``report_overview`` / ``report_preview`` /
``report_download`` / 兼容旧接口 ``/api/report/{rid}``。

委托给 ``engines/report`` (原 ``report_gen.py``)。
返回字段与重构前一致；下载所需的 Content-Disposition 在 router 层处理。
"""
from __future__ import annotations

from typing import Any, Dict

from app.core.exceptions import NotFoundError, ValidationError
from app.engines import report_engine
from app.repositories import get_risk_repo


class ReportService:
    def __init__(self) -> None:
        self.risk_repo = get_risk_repo()

    def overview(self) -> Dict[str, Any]:
        risks = [{"id": r["id"], "name": r["name"], "mileage": r["mileage"],
                  "type_cn": r["type_cn"], "level": r["risk_level"]}
                 for r in self.risk_repo.all_risks()]
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
                {"id": "risk", "name": "单风险报告",
                 "desc": "聚焦单个风险的多源证据与建议"},
            ],
            "risks": risks,
        }

    def preview(self, scope: str = "full", rid: str | None = None) -> Dict[str, Any]:
        try:
            return report_engine.preview_report(scope=scope, rid=rid)
        except ValueError as e:
            raise ValidationError(str(e))

    def generate(self, scope: str = "full", rid: str | None = None,
                 fmt: str = "docx") -> Dict[str, Any]:
        try:
            return report_engine.generate_report(scope=scope, rid=rid, fmt=fmt)
        except ValueError as e:
            raise ValidationError(str(e))

    def legacy_risk(self, rid: str, download: int = 0) -> Dict[str, Any]:
        """兼容旧接口 ``/api/report/{rid}``。"""
        if not self.risk_repo.risk_by_id(rid):
            raise NotFoundError(f"风险对象 {rid} 不存在")
        if download:
            return self.generate(scope="risk", rid=rid, fmt="md")
        return self.preview(scope="risk", rid=rid)
