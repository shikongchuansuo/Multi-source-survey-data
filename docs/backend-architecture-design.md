# 多源勘察数据融合系统 —— 后端架构设计方案

> **文档定位**：本文档是后端重构的**唯一架构契约**。在保持现有功能与对外 API 完全不变的前提下，把单体 `backend/app.py` 重构为清晰的 **API → Service → Repository → Model** 四层架构；引入 PostgreSQL+PostGIS 承载元数据与空间要素（栅格/点云仍走文件存储）；补齐配置层、日志、统一异常处理；最终仍为**一键启动的竞赛/演示系统**（够用且优雅）。
>
> 后续按 §十一 路线图逐项落地时，直接对照本文档执行，无需再做架构决策。

---

## 一、设计目标与约束

| 维度 | 决策 | 说明 |
|---|---|---|
| 技术栈 | 保持 **FastAPI + Python 3.9/3.10** | 沿用 numpy/pandas/scikit-learn/python-docx；与离线 NLU 天然契合 |
| 持久化 | **PostgreSQL 16 + PostGIS 3** | 仅元数据 + 空间几何要素；栅格(PNG/PLY/CSV)仍为文件 |
| 分层粒度 | **轻量分层** | 业务逻辑零改动地从 `app.py` 迁到 `services/`，计算引擎模块原样保留 |
| 交付形式 | **设计文档 + 后续实现路线图** | 本文件 |
| 部署 | **Docker Compose 一键启动** | app + postgres；保留 `run.bat` 单机离线兜底 |
| 行为兼容 | **逐字节一致** | 所有 `/api/*` 端点、请求/响应字段、文件路径完全不变，前端零改动 |

**核心原则**：可解释、可追溯（"基于证据表"）、离线可用、单一工程坐标系统一。

**关键不变量**（贯穿全程的红线）：
1. 前端零改动
2. 对外 API 字段逐字节一致
3. `run.bat` 离线兜底永不破坏
4. 计算引擎（nlu/report/profile/structures3d）逻辑零改动

---

## 二、现状分析（重构基线）

### 2.1 现有模块

| 文件 | 行数 | 职责 | 重构后归属 |
|---|---|---|---|
| `backend/app.py` | 552 | 单体：路由 + 业务 + 数据加载 + 评分 | 拆分到 `routers/` + `services/` |
| `backend/nlu.py` | 499 | NLU/RAG/多轮对话 | `engines/nlu/`（原样保留） |
| `backend/report_gen.py` | 681 | Word/MD/HTML 报告 | `engines/report/`（原样保留） |
| `backend/profile.py` | 154 | 沿线地质纵剖面 | `engines/geo/profile.py`（原样保留） |
| `backend/structures3d.py` | 177 | 三维地质结构 | `engines/geo/structures3d.py`（原样保留） |
| `backend/generate_data.py` | 713 | 样例数据生成器 | `scripts/generate_data.py`（离线工具） |

### 2.2 现有问题（重构动机）

1. **单文件耦合**：`app.py` 同时承担路由 / 业务 / 数据访问 / 评分四职，552 行难以维护扩展。
2. **数据访问硬编码**：`_load()` 直接读 JSON 到模块级全局（`MANIFEST` / `RISK_BY_ID` 等），无抽象层，无法替换为 DB。
3. **无配置层**：路径、端口硬编码；无 `.env`、无 dev/prod 区分。
4. **无统一异常 / 日志**：散落的 `HTTPException`，无结构化日志、无请求追踪。
5. **无空间查询能力**：里程 / 坐标范围查询靠 Python 遍历，无法支撑"真实数据接入"时的空间检索。
6. **模块加载时副作用**：`import app` 即读盘 + 构建 TF-IDF 矩阵，启动慢、难测试。

---

## 三、目标架构总览

```
┌─────────────────────────────────────────────────────────────┐
│                       前端 (frontend/)                        │  ← 零改动
│            fetch('/api/*') + /data/* + /static/*              │
└──────────────────────────┬──────────────────────────────────┘
                           │ HTTP (同源)
┌──────────────────────────▼──────────────────────────────────┐
│  backend/app/  ← 新包根 (取代 backend/app.py)                  │
│                                                               │
│  main.py            应用工厂: 创建 FastAPI, 挂路由/中间件       │
│  core/              横切关注点                                 │
│    ├ config.py      Settings (pydantic-settings, 读 .env)     │
│    ├ logging.py     结构化日志 (loguru, 请求ID注入)            │
│    ├ exceptions.py  业务异常基类 + 全局异常处理器              │
│    └ lifespan.py    启动钩子: 连DB / 预热NLU / 校验数据        │
│                                                               │
│  api/               表现层 (薄)                               │
│    ├ deps.py        依赖注入: get_repo/get_service            │
│    └ routers/       每个领域一个 router                        │
│        ├ manifest.py    borehole.py   geophysics.py           │
│        ├ risk.py    chat.py    report.py   search.py          │
│        ├ analytics.py (risk_scores/3d/profile)                │
│        └ health.py                                       │
│                                                               │
│  services/          业务层 (承载原 app.py 的全部逻辑)          │
│    ├ manifest_service.py  risk_service.py                    │
│    ├ borehole_service.py  geophysics_service.py              │
│    ├ search_service.py    analytics_service.py (评分)        │
│    └ chat_service.py      report_service.py                 │
│                                                               │
│  repositories/      数据访问层 (PG + 文件双源)                 │
│    ├ project_repo.py    risk_repo.py    borehole_repo.py     │
│    ├ geophysics_repo.py report_repo.py   search_repo.py      │
│    └ file_store.py      ← 栅格/点云/CSV 文件读写抽象          │
│                                                               │
│  models/            数据模型层                                 │
│    ├ orm/           SQLAlchemy 2.0 ORM (PG 表)               │
│    │   ├ project.py risk.py borehole.py geophysics.py        │
│    │   └ report.py  base.py                                  │
│    ├ schemas/       Pydantic 响应模型 (API 契约)              │
│    └ dto.py         服务层内部传输对象                        │
│                                                               │
│  engines/           计算引擎 (原样保留, 仅入口调整)             │
│    ├ nlu/           (= 现 nlu.py)                            │
│    ├ report/        (= 现 report_gen.py)                     │
│    └ geo/           profile.py + structures3d.py             │
│                                                               │
│  db/                数据库基础设施                             │
│    ├ session.py     async/sync engine, SessionLocal          │
│    └ migrations/    Alembic 迁移目录                          │
│                                                               │
│  static_assets.py   /data /static /lib 挂载 (替代原 mount)    │
└─────────────────────────────────────────────────────────────┘
                           │
        ┌──────────────────┼──────────────────┐
        ▼                  ▼                  ▼
   PostgreSQL 16      backend/data/       engines/
   (元数据+空间)      (栅格/PLY/CSV)      (TF-IDF/剖面/3D)
```

**依赖方向**（严格单向，禁止反向）：
- `api → services → repositories → models/orm`
- `engines` 被 `services` 调用，不反向依赖任何上层
- `core` 被所有层依赖

---

## 四、分层职责

### 4.1 `api/routers/`（表现层，薄）

- **只做**：参数校验、调用 service、返回 Pydantic schema、HTTP 异常映射。
- **不含**业务逻辑。每个 router ≈ 原 `app.py` 的一组端点。
- 示例：`risk.py` 承载 `GET /api/risk/{rid}`、`GET /api/risk_scores`。

### 4.2 `services/`（业务层）

- 承载原 `app.py` 的全部业务：证据卡组装、多维评分（`_score_risk`）、物探网格构建、问答模板、对话调度。
- 调用 `repositories` 取数、调用 `engines` 计算。
- **无 HTTP 概念**（不 import fastapi），便于单测。

### 4.3 `repositories/`（数据访问层）

- 对 PG 的 CRUD（基于 SQLAlchemy ORM）+ 空间查询（PostGIS `ST_*`）。
- `file_store.py` 统一封装栅格 / PLY / CSV 的路径解析与读流，替代散落的 `os.path.join(DATA, ...)`。
- 提供 "PG miss → 回退文件 JSON" 的过渡策略（见 §八）。

### 4.4 `models/`

- `orm/`：SQLAlchemy 2.0 声明式映射，对应 PG 表（见 §六）。
- `schemas/`：Pydantic v2 响应模型，与现有 JSON 字段**一一对应**（保证前端零改动）。

### 4.5 `engines/`（计算引擎，原样保留）

- `nlu/`、`report/`、`geo/profile.py`、`geo/structures3d.py` 直接迁移。
- 唯一改动：把模块级 `_load(...)` 全局加载改为**惰性初始化函数**（如 `get_nlu_engine()`），由 `lifespan` 在启动时预热并缓存，避免 import 副作用。

---

## 五、核心横切关注点

### 5.1 配置层 `core/config.py`

```python
class Settings(BaseSettings):
    # 应用
    app_name: str = "多源勘察数据联动展示与证据链追溯系统"
    env: Literal["dev", "prod"] = "dev"
    host: str = "0.0.0.0"
    port: int = 8000
    # 路径
    project_root: Path          # 自动推断
    data_dir: Path              # backend/data
    frontend_dir: Path          # frontend/
    # 数据库
    database_url: str = "postgresql+psycopg://fusion:fusion@localhost:5432/fusion"
    pg_echo: bool = False
    # 功能开关
    use_db: bool = True         # False = 纯文件模式(兼容旧 run.bat)
    cors_origins: list[str] = ["*"]
    model_config = SettingsConfigDict(env_file=".env", env_prefix="FUSION_")
```

- 通过 `FUSION_*` 环境变量覆盖；`.env` 进 `.gitignore`，提供 `.env.example`。
- `use_db=False` 时退化为纯文件模式 —— **保证 `run.bat` 离线兜底永不破坏**。

### 5.2 日志 `core/logging.py`

- `loguru` + 请求中间件注入 `request_id`，所有日志带 trace。
- 统一格式：`时间 | LEVEL | request_id | 模块 | 消息`。

### 5.3 异常 `core/exceptions.py`

```
AppError(基类) → NotFoundError / ValidationError / EngineError
```

- 全局 exception handler 把 `AppError` 映射为 `HTTPException`，避免 service 层 import fastapi。
- 兜底 500 handler 记录完整堆栈。

### 5.4 生命周期 `core/lifespan.py`

启动顺序：
1. 加载 Settings
2. 连 PG（`use_db=True` 时）
3. 校验 `data_dir` 完整性
4. 预热 NLU（构建 TF-IDF）
5. 预构建 DEM 网格缓存

---

## 六、数据模型（PostgreSQL + PostGIS）

> 仅入**元数据 + 空间几何要素**。栅格(PNG)、点云(PLY)、物探原始网格(CSV)仍存文件，DB 只存**相对路径引用**。
>
> 工程局部坐标系 SRID 统一记为 `0`（自定义本地系，X 米向东 / Y 米向北）。

### 6.1 表设计

**projects**（项目 / 工程场景，当前 1 行）

| 列 | 类型 | 说明 |
|---|---|---|
| id | serial PK | |
| code | text unique | 如 `XX_TUNNEL_K12` |
| name, subtitle, scenario | text | manifest#project |
| coordinate_note, mileage_note | text | |
| srid | int | 工程局部坐标系 SRID（自定义，默认 0） |
| extent_geom | geometry(Polygon, 0) | PostGIS，区域 1000×800m 外接矩形 |

**routes**（线路，1:1 project）

| 列 | 类型 | 说明 |
|---|---|---|
| id, project_id FK | | |
| type, name, start_mileage, end_mileage | text | |
| centerline_geom | geometry(LineString, 0) | 21 点中心线 |
| portals_json | jsonb | 进 / 出口信息 |

**risk_objects**（风险对象，核心）

| 列 | 类型 | 说明 |
|---|---|---|
| id | text PK | R001 / R002 / R003 |
| project_id FK | | |
| name, type, type_cn, risk_level, confidence | text | |
| mileage | text | "K12+380" |
| mileage_m | numeric | 12380（**建索引**） |
| center_geom | geometry(Point, 0) | PostGIS |
| polygon_geom | geometry(Polygon, 0) | 风险区边界 |
| borehole_ids | text[] | 关联钻孔 |
| geophysics_line_id | text FK? | 关联测线 |
| evidence_json | jsonb | 五源证据 + params |
| interpretation, design_suggestion | text | |

**boreholes**（钻孔）

| 列 | 类型 | 说明 |
|---|---|---|
| id(text PK), project_id, mileage, mileage_m, depth_m, elevation, water_depth_m | | |
| location_geom | geometry(Point, 0) | 孔口 XY |
| layers_json | jsonb | 分层结构 |

**geophysics_lines**（物探测线）

| 列 | 类型 | 说明 |
|---|---|---|
| id(text PK), project_id, name, method, length_m, rho_min, anomaly_depth_m | | |
| image_path, csv_path | text | 相对 data_dir |
| axis_geom | geometry(LineString, 0) | 测线空间位置 |

**report_sections**（报告段落）

| 列 | 类型 | 说明 |
|---|---|---|
| id(text PK), project_id, title, content | | |
| related_risks | text[] | |

**data_sources**（数据源清单，驱动 UI FAB 面板）

| 列 | 类型 | 说明 |
|---|---|---|
| id, project_id, name, kind | text | |
| file_path | text | 相对 data_dir |
| meta_json | jsonb | meta.json 内容 |

**chat_sessions**（可选，对话历史持久化；当前为内存，未来扩展）

| 列 | 类型 | 说明 |
|---|---|---|
| session_id(text PK), project_id | | |
| history_json | jsonb | |
| last_risk_id | text | |
| updated_at | timestamptz | |

### 6.2 ER 关系

```
projects 1───1 routes
projects 1───N risk_objects ──N─── boreholes (通过 borehole_ids)
projects 1───N boreholes
projects 1───N geophysics_lines
projects 1───N report_sections
projects 1───N data_sources
risk_objects N───1 geophysics_lines (geophysics_line_id)
```

### 6.3 PostGIS 空间能力（新增价值）

| 用途 | PostGIS 函数 | 替代的现有 Python 遍历 |
|---|---|---|
| 按坐标匹配最近风险 | `ST_DWithin(center_geom, pt, D)` | nlu 中按里程 250m 遍历匹配 |
| 里程范围筛选风险 / 钻孔 | `ST_Intersects(geom, bbox)` | `query_by_mileage` 的 Python 遍历 |
| 钻孔投影到线路 | `ST_LineLocatePoint(centerline, pt)` | profile.py 的 `np.argmin(d)` |

### 6.4 迁移与数据装载

- **Alembic** 管理 schema 版本；初始迁移建表 + 建空间索引（`CREATE INDEX ... USING GIST`）。
- **数据装载脚本** `scripts/seed.py`：读 `backend/data/*.json` → ORM upsert → PG（幂等，可重复运行）。

---

## 七、API 清单与归属（行为不变）

| 端点 | 新归属 router | 新归属 service |
|---|---|---|
| `GET /api/manifest` | manifest.py | manifest_service |
| `GET /api/risk/{rid}` | risk.py | risk_service |
| `GET /api/boreholes[?bid]` | borehole.py | borehole_service |
| `GET /api/geophysics[?lid]` | geophysics.py | geophysics_service |
| `GET /api/geophysics/{lid}/grid` | geophysics.py | geophysics_service (读 CSV) |
| `GET /api/search` | search.py | search_service |
| `POST /api/qa` | chat.py | chat_service |
| `POST /api/chat` | chat.py | chat_service (调 engines/nlu) |
| `GET /api/chat/suggest` | chat.py | chat_service |
| `GET /api/report[/preview/download]` | report.py | report_service (调 engines/report) |
| `GET /api/risk_scores[?rid]` | analytics.py | analytics_service (`_score_risk`) |
| `GET /api/profile/route` | analytics.py | analytics_service (调 engines/geo) |
| `GET /api/3d/structures` | analytics.py | analytics_service |
| `GET /api/3d/terrain` | analytics.py | analytics_service |
| `GET /api/health` | health.py | — |
| `/` `/ui` `/static` `/lib` `/data` | static_assets.py | file_store |

**关键保证**：每个端点的 URL、方法、查询参数、响应 JSON 字段名 / 结构**与现状逐字节一致**（由 Pydantic schema 锁定），前端 `app.js` 无需任何改动。

---

## 八、迁移与兼容策略（低风险、可回滚）

**双源过渡**：repository 层先实现 "PG 优先，miss 回退文件 JSON"。`settings.use_db=False` 直接走纯文件模式（= 现状）。

1. **第一阶段（重构）**：`use_db=False`，纯文件，验证分层不破坏行为。
2. **第二阶段（接 PG）**：`use_db=True`，跑 `seed.py` 装数据，逐表比对 PG 结果 vs 文件结果一致。
3. **第三阶段（用空间）**：逐步把 Python 遍历查询换成 PostGIS 查询，A/B 验证。

**计算引擎零改动**：nlu / report / profile / structures3d 不动逻辑，仅把模块级加载改惰性。`generate_data.py` 移到 `scripts/`，作为离线数据准备工具，不进运行时路径。

---

## 九、部署（Docker Compose 一键，竞赛友好）

```yaml
# docker-compose.yml
services:
  db:
    image: postgis/postgis:16-3.4
    environment:
      POSTGRES_USER: fusion
      POSTGRES_PASSWORD: fusion
      POSTGRES_DB: fusion
    volumes: [pgdata:/var/lib/postgresql/data]
    ports: ["5432:5432"]

  app:
    build: .
    depends_on: [db]
    environment:
      FUSION_DATABASE_URL: postgresql+psycopg://fusion:fusion@db:5432/fusion
      FUSION_USE_DB: "true"
    ports: ["8000:8000"]
    volumes:
      - ./backend/data:/app/backend/data
      - ./frontend:/app/frontend

volumes:
  pgdata: {}
```

- `Dockerfile` 基于 `python:3.10-slim` + `requirements.txt`。
- **`run.bat` 保留**：检测无 Docker 时仍可 `pip install + uvicorn`（`use_db=False`）单机离线跑 —— **演示永不翻车**。

---

## 十、依赖清单（requirements.txt）

```
# 既有
fastapi
uvicorn[standard]
numpy
pandas
scikit-learn
python-docx
pillow
matplotlib

# 新增
SQLAlchemy>=2.0
Alembic
psycopg[binary]
pydantic-settings
loguru

# 测试（可选）
pytest
httpx
```

---

## 十一、实现路线图（建议分 5 步，每步可独立验证）

| 步骤 | 内容 | 验证标准 |
|---|---|---|
| **Step 1｜骨架搭建（不改行为）** | 新建 `backend/app/` 包结构，`main.py` 应用工厂，`core/{config,logging,exceptions,lifespan}`，把 `app.py` 整体作为 `legacy.py` 挂回 | 启动 = 现状，前端功能全通 |
| **Step 2｜分层抽取** | 按 §四 / §七 把端点逐组从 `legacy.py` 迁到 `routers/ + services/`，业务逻辑原样搬运，`use_db=False` 走文件 | 每迁一组回归测一次前端 |
| **Step 3｜PG 接入** | 写 `models/orm` + Alembic 初始迁移 + `scripts/seed.py`，repository 实现 PG / 文件双源，`use_db=True` 跑通 | PG 结果 = 文件结果 |
| **Step 4｜空间查询替换** | 把里程匹配 / 范围筛选 / 钻孔投影换成 PostGIS | A/B 比对结果一致 |
| **Step 5｜容器化与文档** | Dockerfile + docker-compose + 更新 README + `.env.example` | `docker compose up` 一键可用 |

---

## 十二、交付物

本方案即**唯一交付物**（设计文档）。文档已覆盖：
- 现状基线（§二）
- 四层架构与目录结构（§三、§四）
- 各层职责（§四）
- PG / PostGIS 表设计与 ER（§六）
- API 归属映射（§七）
- 迁移与兼容策略（§八）
- 部署（§九）
- 依赖（§十）
- 分步路线图（§十一）

> **关键不变量**：前端零改动 · 对外 API 字段逐字节一致 · `run.bat` 离线兜底永不破坏 · 计算引擎零改动。
