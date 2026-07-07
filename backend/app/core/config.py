# -*- coding: utf-8 -*-
"""集中式配置层。

通过 ``FUSION_*`` 环境变量或 ``.env`` 文件覆盖，统一管理所有路径、
端口、数据库连接与功能开关。

设计要点
--------
- ``use_db=False`` 时退化为**纯文件模式**（= 现状），保证 ``run.bat``
  离线兜底永不破坏。这是贯穿整个重构的兼容性红线。
- 路径默认自动推断，无需用户配置即可在仓库根目录运行。
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Literal, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def _infer_project_root() -> Path:
    """推断仓库根目录（含 backend/ 与 frontend/ 的那一层）。"""
    here = Path(__file__).resolve()
    # app/core/config.py -> app/core -> app -> backend -> <root>
    return here.parents[3]


class Settings(BaseSettings):
    """全局配置。所有字段均可被 ``FUSION_<FIELD>`` 环境变量覆盖。"""

    # ---- 应用 ----
    app_name: str = "多源勘察数据联动展示与证据链追溯系统"
    env: Literal["dev", "prod"] = "dev"
    host: str = "0.0.0.0"
    port: int = 8000
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])

    # ---- 路径（运行时推断，亦可被环境变量覆盖）----
    # 注意：pydantic-settings 会把字符串自动转 Path。
    project_root: Path = Field(default_factory=_infer_project_root)
    backend_dir: Optional[Path] = None
    data_dir: Optional[Path] = None
    frontend_dir: Optional[Path] = None
    legacy_data_dir: Optional[Path] = None  # backend/data，兼容 engines 旧模块

    # ---- 数据库 ----
    database_url: str = (
        "postgresql+psycopg://fusion:fusion@localhost:5432/fusion"
    )
    pg_echo: bool = False

    # ---- 功能开关 ----
    # True=PostgreSQL 模式（PG 优先，文件回退）
    # False=纯文件模式（兼容旧 run.bat 单机离线）
    use_db: bool = False

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="FUSION_",
        extra="ignore",
    )

    def model_post_init(self, __ctx) -> None:  # noqa: D401
        """填充派生路径，确保绝对路径。"""
        root = self.project_root
        if self.backend_dir is None:
            self.backend_dir = root / "backend"
        if self.frontend_dir is None:
            self.frontend_dir = root / "frontend"
        if self.data_dir is None:
            self.data_dir = self.backend_dir / "data"
        if self.legacy_data_dir is None:
            self.legacy_data_dir = self.backend_dir / "data"
        # 规范化为绝对路径
        for f in ("project_root", "backend_dir", "data_dir",
                  "frontend_dir", "legacy_data_dir"):
            setattr(self, f, Path(getattr(self, f)).resolve())


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回单例 Settings（缓存在进程内）。"""
    return Settings()  # type: ignore[call-arg]
