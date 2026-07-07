# -*- coding: utf-8 -*-
"""关键词检索业务。对应原 ``app.py::search``。"""
from __future__ import annotations

from typing import Any, Dict

from app.repositories import get_search_repo


class SearchService:
    def __init__(self) -> None:
        self.repo = get_search_repo()

    def search(self, q: str) -> Dict[str, Any]:
        return self.repo.search(q)
