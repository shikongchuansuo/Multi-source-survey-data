# -*- coding: utf-8 -*-
"""数据模型层。

- ``orm/``     SQLAlchemy 2.0 ORM 映射（PostgreSQL 表）。
- ``schemas/`` Pydantic v2 响应模型（API 契约）。

当前 service 层直接返回 dict（与原 app.py 一致），schemas 作为**可选**的
响应契约在此声明，便于后续逐步启用 ``response_model=...``。
"""
