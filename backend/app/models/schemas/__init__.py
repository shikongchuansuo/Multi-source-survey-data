# -*- coding: utf-8 -*-
"""Pydantic 响应模型（API 契约）。

声明在此，便于后续逐步给 router 加 ``response_model=...`` 以锁定输出结构。
当前 service 层直接返回 dict（与原 app.py 一致），schemas 作为文档化的
字段契约。
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class ManifestResponse(BaseModel):
    project: dict
    route: dict
    data_sources: list
    dem: dict
    orthophoto: dict
    pointcloud: dict
    risks: list
    stats: dict


class EvidenceCard(BaseModel):
    source: str
    icon: str
    content: str
    file: Optional[Any] = None
    kind: str
    extra: Optional[Any] = None


class RiskDetailResponse(BaseModel):
    risk: dict
    boreholes: list
    geophysics: Optional[dict] = None
    report_sections: list
    evidence_cards: list[EvidenceCard]


class ChatResponse(BaseModel):
    session_id: str
    intent: Optional[str] = None
    answer: str
    actions: list = Field(default_factory=list)
    evidence_refs: list = Field(default_factory=list)
    matched_risk: Optional[str] = None


class QAResponse(BaseModel):
    question: str
    answered: bool
    answer: str
    evidence_refs: list = Field(default_factory=list)
    matched_risks: Optional[list] = None


class HealthResponse(BaseModel):
    status: str
    data_root: str
    risk_count: int
    borehole_count: int
    report_formats: list
