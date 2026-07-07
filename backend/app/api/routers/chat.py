# -*- coding: utf-8 -*-
"""对话路由 ``/api/qa``、``/api/chat``、``/api/chat/suggest``。"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.api.deps import get_chat_service
from app.services.chat_service import ChatService

router = APIRouter()


class QAReq(BaseModel):
    question: str


class ChatReq(BaseModel):
    message: str
    session_id: Optional[str] = "default"


@router.post("/api/qa")
def qa(req: QAReq, svc: ChatService = Depends(get_chat_service)):
    """证据链问答（基于证据表的模板回答）。"""
    return svc.qa(req.question)


@router.post("/api/chat")
def chat(req: ChatReq, svc: ChatService = Depends(get_chat_service)):
    """智能对话（NLU 意图识别 + RAG + 多轮对话）。"""
    return svc.chat(req.message, req.session_id)


@router.get("/api/chat/suggest")
def chat_suggest(svc: ChatService = Depends(get_chat_service)):
    """推荐问题示例。"""
    return svc.suggestions()
