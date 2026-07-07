# -*- coding: utf-8 -*-
"""API 等价性验证脚本。

用 TestClient 同时访问**新旧两个 app**的所有 /api/* 端点，逐字段比对
JSON 响应，验证重构是否破坏对外行为（设计文档核心准则）。

用法::

    python -m backend.scripts.verify_api_equivalence

退出码 0 = 全部一致；非 0 = 存在差异。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_ROOT / "backend"))

# 强制纯文件模式，保证新旧 app 在同一数据源下对比
os.environ.setdefault("FUSION_USE_DB", "false")


def _build_clients():
    # ---- 新 app（分层重构版）----
    from app.main import create_app
    new_app = create_app()
    from fastapi.testclient import TestClient
    new = TestClient(new_app)

    # ---- 旧 app（单体 legacy 版）----
    # 旧 app.py 模块名已被 app 包占用，直接从 app_legacy 加载
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "app_legacy", _ROOT / "backend" / "app_legacy.py")
    mod = importlib.util.module_from_spec(spec)
    # 旧模块在 import 时读 backend/data，已设好 cwd 与 sys.path
    sys.modules["app_legacy"] = mod
    spec.loader.exec_module(mod)
    old = TestClient(mod.app)
    return old, new


def _cmp(name, a, b, path="$"):
    """递归比对，返回不一致列表。"""
    diffs = []
    if type(a) != type(b):
        # 容忍 int/float 数值等价
        if isinstance(a, (int, float)) and isinstance(b, (int, float)) \
                and abs(a - b) < 1e-6:
            return diffs
        return [(f"{name}@{path}", f"type {type(a).__name__} != {type(b).__name__}",
                 a, b)]
    if isinstance(a, dict):
        keys = set(a) | set(b)
        for k in keys:
            if k not in a:
                diffs.append((f"{name}@{path}.{k}", "missing in new", None, b[k]))
            elif k not in b:
                diffs.append((f"{name}@{path}.{k}", "missing in old", a[k], None))
            else:
                diffs += _cmp(name, a[k], b[k], f"{path}.{k}")
    elif isinstance(a, list):
        if len(a) != len(b):
            diffs.append((f"{name}@{path}", f"len {len(a)} != {len(b)}", a, b))
        else:
            for i, (x, y) in enumerate(zip(a, b)):
                diffs += _cmp(name, x, y, f"{path}[{i}]")
    else:
        if a != b:
            # 数值容忍
            if isinstance(a, (int, float)) and abs(a - b) < 1e-6:
                pass
            else:
                diffs.append((f"{name}@{path}", f"{a!r} != {b!r}", a, b))
    return diffs


CASES = [
    ("GET",  "/api/manifest",                    {}, None),
    ("GET",  "/api/risk/R001",                   {}, None),
    ("GET",  "/api/risk/R002",                   {}, None),
    ("GET",  "/api/risk/R003",                   {}, None),
    ("GET",  "/api/boreholes",                   {}, None),
    ("GET",  "/api/boreholes",                   {"bid": "ZK3"}, None),
    ("GET",  "/api/geophysics",                  {}, None),
    ("GET",  "/api/geophysics",                  {"lid": "L1"}, None),
    ("GET",  "/api/geophysics/L1/grid",          {}, None),
    ("GET",  "/api/geophysics/L2/grid",          {}, None),
    ("GET",  "/api/search",                      {"q": "边坡"}, None),
    ("GET",  "/api/search",                      {"q": "富水"}, None),
    ("GET",  "/api/risk_scores",                 {}, None),
    ("GET",  "/api/risk_scores",                 {"rid": "R001"}, None),
    ("GET",  "/api/profile/route",               {}, None),
    ("GET",  "/api/3d/structures",               {}, None),
    ("GET",  "/api/3d/terrain",                  {"step": 5}, None),
    ("GET",  "/api/report",                      {}, None),
    ("GET",  "/api/report/preview",              {"scope": "full"}, None),
    ("GET",  "/api/report/preview",              {"scope": "risk", "rid": "R001"}, None),
    ("GET",  "/api/health",                      {}, None),
    ("GET",  "/api/chat/suggest",                {}, None),
    ("POST", "/api/qa",                          {}, {"question": "K12+380 为什么是高风险"}),
    ("POST", "/api/qa",                          {}, {"question": "全线有哪些风险"}),
    ("POST", "/api/chat",                        {}, {"message": "带我去看看 K12+380 的边坡"}),
    ("POST", "/api/chat",                        {}, {"message": "坡度大于 30 度的风险有哪些"}),
    ("POST", "/api/chat",                        {}, {"message": "R001 和 R002 哪个风险更高"}),
]


def main() -> int:
    old, new = _build_clients()
    total = 0
    failed = 0
    all_diffs = []
    for method, path, params, body in CASES:
        total += 1
        if method == "GET":
            ro = old.get(path, params=params)
            rn = new.get(path, params=params)
        else:
            ro = old.post(path, json=body, params=params)
            rn = new.post(path, json=body, params=params)
        if ro.status_code != rn.status_code:
            failed += 1
            all_diffs.append((f"{method} {path} {params} {body}",
                              f"status {ro.status_code} != {rn.status_code}",
                              ro.text[:200], rn.text[:200]))
            continue
        if ro.status_code >= 400:
            # 两者都报错且码相同 —— 记录但不算失败（除非内容差异大）
            continue
        try:
            jo, jn = ro.json(), rn.json()
        except Exception as exc:
            failed += 1
            all_diffs.append((f"{method} {path}", f"json decode: {exc}",
                              ro.text[:200], rn.text[:200]))
            continue
        diffs = _cmp(f"{method} {path}", jo, jn)
        if diffs:
            failed += 1
            all_diffs.append((f"{method} {path} {params} {body}",
                              f"{len(diffs)} field diffs", diffs[:5], None))

    print(f"\n{'='*70}")
    print(f"API 等价性验证: {total - failed}/{total} 通过")
    print(f"{'='*70}")
    for name, msg, a, b in all_diffs:
        print(f"\n[FAIL] {name}")
        print(f"       {msg}")
        if isinstance(a, list) and a and isinstance(a[0], tuple):
            for d in a:
                print(f"       - {d[0]}: {d[1]} (old={d[2]!r} new={d[3]!r})")
        else:
            print(f"       old: {str(a)[:300]}")
            print(f"       new: {str(b)[:300]}")

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
