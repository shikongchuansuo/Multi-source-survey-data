# -*- coding: utf-8 -*-
"""多源勘察数据融合系统 —— 后端应用包。

包结构（详见 docs/backend-architecture-design.md）::

    app/
      main.py            应用工厂
      core/              配置 / 日志 / 异常 / 生命周期
      api/routers/       表现层 (薄)
      services/          业务层
      repositories/      数据访问层 (PG + 文件双源)
      models/            ORM + Pydantic schema
      engines/           计算引擎 (nlu / report / geo)
      db/                数据库基础设施
      static_assets.py   静态资源挂载

导入兼容性
----------
本包内部统一使用 ``from app.xxx import ...`` 形式的绝对导入。本引导代码
把 ``backend/`` 加入 ``sys.path``，并将包对象注册为顶层 ``app``，使两种
启动方式都能正常解析且**不产生模块重复**::

    uvicorn backend.app.main:app        # 从仓库根（backend.app 导入）
    cd backend && uvicorn app.main:app  # 从 backend/（app 导入）
"""
from __future__ import annotations

import os
import sys

# 1) 把 backend/ 加入 sys.path，使 ``import app`` 可解析
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# 2) 把本包注册为顶层 ``app``，避免以 ``backend.app`` 导入时
#    ``from app.xxx`` 又重新加载一份（模块重复会导致 lru_cache / 单例错乱）。
#    仅在尚未注册时设置，保持幂等。
_self = sys.modules[__name__]
if "app" not in sys.modules:
    sys.modules["app"] = _self

# 3) 真正的应用实例构造在 main.py 中完成
from app.main import app, create_app  # noqa: E402,F401

__all__ = ["app", "create_app"]
