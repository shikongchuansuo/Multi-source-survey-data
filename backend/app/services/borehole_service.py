# -*- coding: utf-8 -*-
"""钻孔业务。对应原 ``app.py::get_boreholes``。"""
from __future__ import annotations

from typing import Any, Dict

from app.core.exceptions import NotFoundError
from app.repositories import get_borehole_repo


class BoreholeService:
    def __init__(self) -> None:
        self.repo = get_borehole_repo()

    def list_or_get(self, bid: str | None = None) -> Dict[str, Any]:
        if bid:
            b = self.repo.borehole_by_id(bid)
            if not b:
                raise NotFoundError(f"钻孔 {bid} 不存在")
            return b
        return {"boreholes": self.repo.all_boreholes()}
