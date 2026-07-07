# -*- coding: utf-8 -*-
"""report_sections / data_sources 表（设计文档 §6.1）。"""
from __future__ import annotations

from typing import Optional

from sqlalchemy import Integer, String, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.models.orm.base import Base, JSONVariant, TextArrayVariant


class ReportSection(Base):
    __tablename__ = "report_sections"

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text)
    related_risks: Mapped[list] = mapped_column(TextArrayVariant, default=list)


class DataSource(Base):
    __tablename__ = "data_sources"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_id: Mapped[int] = mapped_column(ForeignKey("projects.id"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(32))
    file_path: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    meta_json: Mapped[Optional[dict]] = mapped_column(JSONVariant, nullable=True)
