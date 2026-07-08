# -*- coding: utf-8 -*-
"""计算引擎包。

封装现有计算模块（``backend/nlu.py``、``backend/report_gen.py``、
``backend/profile.py``、``backend/structures3d.py``），通过惰性加载避免
import 时的磁盘 I/O 副作用。

设计原则（见 docs/backend-architecture-design.md §4.5）：
- 计算引擎逻辑**原样保留**，零改动。
- 仅把"模块级 `_load(...)` 全局加载"改为惰性初始化函数。
- 由 ``core/lifespan`` 在启动时预热并缓存。

访问方式::

    from app.engines import nlu_engine
    answer = nlu_engine.generate_response(msg, sid=...)
"""
from __future__ import annotations

from app.engines.loader import (
    get_nlu,
    get_report,
    get_profile,
    get_structures3d,
    get_voxel,
    get_fusion,
    get_ontology,
    get_landcover,
    preload_engines,
    release_engines,
)

__all__ = [
    "get_nlu", "get_report", "get_profile", "get_structures3d", "get_voxel",
    "get_fusion", "get_ontology", "get_landcover",
    "preload_engines", "release_engines",
    "nlu_engine", "report_engine", "profile_engine", "structures3d_engine",
    "voxel_engine", "fusion_engine", "ontology_engine", "landcover_engine",
]


class _EngineAccessor:
    """惰性访问器：首次属性访问时触发底层模块加载。

    ``nlu_engine.generate_response(...)`` 等价于先 ``import`` 旧模块再调用，
    但避免了 import 副作用，且加载结果全局缓存。
    """

    __slots__ = ("_kind",)

    def __init__(self, kind: str):
        object.__setattr__(self, "_kind", kind)

    def _mod(self):
        kind = object.__getattribute__(self, "_kind")
        if kind == "nlu":
            return get_nlu()
        if kind == "report":
            return get_report()
        if kind == "profile":
            return get_profile()
        if kind == "structures3d":
            return get_structures3d()
        if kind == "voxel":
            return get_voxel()
        if kind == "fusion":
            return get_fusion()
        if kind == "ontology":
            return get_ontology()
        if kind == "landcover":
            return get_landcover()
        raise AttributeError(kind)

    def __getattr__(self, name):
        return getattr(self._mod(), name)

    def __repr__(self) -> str:
        return f"<EngineAccessor kind={object.__getattribute__(self, '_kind')!r}>"


nlu_engine = _EngineAccessor("nlu")
report_engine = _EngineAccessor("report")
profile_engine = _EngineAccessor("profile")
structures3d_engine = _EngineAccessor("structures3d")
voxel_engine = _EngineAccessor("voxel")
fusion_engine = _EngineAccessor("fusion")
ontology_engine = _EngineAccessor("ontology")
landcover_engine = _EngineAccessor("landcover")
