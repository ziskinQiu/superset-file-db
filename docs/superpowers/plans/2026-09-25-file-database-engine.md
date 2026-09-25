# Superset 文件数据库引擎（file-db）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个不修改 Superset 源代码的扩展（`my-org/file-db`），支持用户拖拽上传 CSV/Excel，配置 schema（列类型/分隔符/编码/工作表），并将其注册为 Superset 数据源（DuckDB 查询引擎 + 自定义 SQLAlchemy 方言），含文件管理、过期清理、权限与完整日志。

**Architecture:** 分层扩展架构：存储层（`StorageBackend` 抽象 + 本地实现）→ 元数据层（Superset PostgreSQL 中的独立表组）→ 解析层（CSV/Excel schema 推断，Excel 惰性转 Parquet）→ 查询引擎（共享 DuckDB 连接 + 每文件视图）→ SQLAlchemy `filedb` 方言（让 Superset 原生 Dataset/SQL Lab 直接查询）→ 服务层（业务编排）→ REST API（`RestApi` 扩展端点）→ React 前端（上传/预览/配置/管理，module federation 注册到 `sqllab.panels`）。全部业务逻辑进服务层，API 只做请求解析与响应封装，保证可脱离 Superset 宿主做单元测试。

**Tech Stack:** Python 3.12 / SQLAlchemy 1.4 / DuckDB / pandas / openpyxl / chardet / Flask + flask-appbuilder（`superset_core.rest_api`）/ React 17 + TypeScript + webpack 5（module federation）/ vitest + pytest。宿主镜像 `apache/superset:6.1.0`，构建产物 `.supx`（`superset-extensions` CLI）。

**Spec:** [docs/superpowers/specs/2026-09-25-file-database-engine-design.md](../specs/2026-09-25-file-database-engine-design.md)

## Global Constraints

- 不修改 Superset 源代码；只通过扩展机制（`extension.json` + `.supx`）交付。
- 宿主：`apache/superset:6.1.0`；扩展安装目录 `/app/extensions`；功能开关 `ENABLE_EXTENSIONS=True`。
- 文件类型仅 `.csv` / `.xls` / `.xlsx`；CSV ≤ 150MB，Excel ≤ 500MB；文件名 ≤ 255 字符且不含特殊字符。
- 文件保留 180 天（`expiry_time = upload_time + 180d`）；删除日志与列类型修改历史**永久保留**。
- 预览固定 100 行；CSV 分隔符可选 `,` `;` `\t` `|` 空格；编码可选 `utf-8` `gbk` `gb2312` `latin-1`（自动检测，失败让用户手动选）。
- 列类型仅 `string` / `integer` / `float` / `datetime` / `boolean`；`datetime` 可带 strptime 格式（如 `%Y-%m-%d`）。
- 上传：批量 + 并行（最多 3 个并发）+ 断点续传（分块 8MB）+ 逐文件进度；Excel 多工作表可多选，每工作表独立数据源；上传后立即创建数据源（用户手动命名，可加描述，标签用 Superset 原生 tag）。
- 权限：复用 Superset 权限体系，不建自定义权限系统；文件删除/配置/列类型修改 = 上传者或 Admin；数据源创建 = 上传者或拥有 Superset 数据源写权限的用户；数据访问权限交给 Superset Dataset 权限（含 RLS/CLS）。
- 元数据存 Superset PostgreSQL（扩展自有表，不改宿主表）；文件默认存本地 `/data/uploads`（Admin 配置大目录，自动建用户子目录）；第一版不支持 GCS，但存储层留接口。
- 开发环境 venv：`/Users/ziskin/Development/superset-ex/.venv`（Python 3.12.10）。**该 venv 无 `superset` 包**——单元测试禁止直接 import `superset.*`，宿主模型一律通过 `host_db.py` 惰性解析 + 测试注入 fake。
- 后端测试命令：`python -m pytest tests -v`（cwd = `file-db/backend`）；前端测试命令：`npm test`（vitest，cwd = `file-db/frontend`）；构建命令：`superset-extensions validate && superset-extensions bundle`（cwd = `file-db`）。
- 工作区当前无 git 仓库：Task 1 Step 6 提交前先执行 `git init`，并创建 `.gitignore`（`.venv/`、`node_modules/`、`dist/`、`*.supx`、`.DS_Store`、`data/`）。
- 全部任务遵循 TDD：先写失败测试 → 确认失败 → 最小实现 → 通过 → commit。commit message 用 `feat:` / `test:` / `fix:` / `chore:` 前缀。

---

## File Structure

```
file-db/                                # 扩展根目录（与 hello-world 同级）
├── extension.json                      # 扩展清单：publisher=my-org, name=file-db
├── Dockerfile                          # 集成镜像（基于 apache/superset:6.1.0）
├── docker-compose.yml                  # 本地 E2E：postgres + superset(含扩展)
├── superset_config.py                  # 宿主配置：ENABLE_EXTENSIONS / PG 元数据库
├── init-superset.sh                    # 容器初始化脚本
├── DEPLOY.md                           # 部署文档
├── backend/
│   ├── pyproject.toml                  # 构建包含规则 + sqlalchemy.dialects 入口点
│   ├── requirement.txt                 # 运行时依赖（装进宿主镜像）
│   ├── requirement-dev.txt             # 测试依赖（装进开发 venv）
│   ├── src/my_org/file_db/
│   │   ├── __init__.py
│   │   ├── entrypoint.py               # 注册 API + 注册 filedb 方言
│   │   ├── config.py                   # 全部常量/限制/映射表
│   │   ├── db.py                       # Base + engine/session 工厂（元数据库）
│   │   ├── models.py                   # 7 张扩展表 ORM
│   │   ├── storage/
│   │   │   ├── __init__.py
│   │   │   ├── base.py                 # StorageBackend ABC
│   │   │   └── local.py                # LocalStorageBackend
│   │   ├── parsers/
│   │   │   ├── __init__.py
│   │   │   ├── schema.py               # ColumnSchema/SheetSchema/FileSchema + 类型推断
│   │   │   ├── csv_parser.py           # 编码/分隔符检测、GBK 转码、schema、行数
│   │   │   └── excel_parser.py         # 工作表列表、schema、Excel→Parquet
│   │   ├── metadata.py                 # MetadataManager（文件/列/工作表/日志）
│   │   ├── upload.py                   # UploadManager（分块会话/校验/落盘/登记）
│   │   ├── query_engine.py             # FileQueryEngine（DuckDB 视图/预览/查询）
│   │   ├── dialect.py                  # FileDBDialect + DBAPI shim + registry 注册
│   │   ├── permissions.py              # 当前用户/owner-admin/数据源创建权限
│   │   ├── host_db.py                  # 宿主 Superset 会话/模型惰性解析（可注入）
│   │   ├── datasource.py               # DatasourceManager（创建/追踪/级联删除数据源）
│   │   ├── cleanup.py                  # 过期清理（节流自动 + Admin 手动）
│   │   ├── services/
│   │   │   ├── __init__.py             # Services 聚合 + build_services()
│   │   │   ├── upload_service.py       # init/chunk/complete/abort
│   │   │   ├── file_service.py         # 列表/详情/预览/配置/usage/删除级联
│   │   │   ├── column_service.py       # 列类型更新/JSON 导入/历史
│   │   │   └── datasource_service.py   # 创建数据源/可选连接/通知/清理入口
│   │   └── api/
│   │       ├── __init__.py
│   │       ├── files_api.py            # 上传 + 文件 + 预览 + 通知端点
│   │       ├── columns_api.py          # 列配置端点
│   │       └── datasources_api.py      # 数据源 + Admin 清理端点
│   └── tests/
│       ├── conftest.py                 # engine/session/storage/app fixtures
│       ├── fixtures/                   # 生成的 CSV/XLSX 样本（测试内动态生成）
│       ├── test_models.py
│       ├── test_storage.py
│       ├── test_csv_parser.py
│       ├── test_excel_parser.py
│       ├── test_metadata.py
│       ├── test_column_history.py
│       ├── test_upload.py
│       ├── test_query_engine.py
│       ├── test_dialect.py
│       ├── test_permissions.py
│       ├── test_datasource.py
│       ├── test_cleanup.py
│       ├── test_services_upload_file.py
│       ├── test_services_columns.py
│       ├── test_services_datasource.py
│       └── test_api.py
└── frontend/
    ├── package.json                    # react-dropzone + vitest 依赖
    ├── tsconfig.json
    ├── webpack.config.js               # module federation（对照 hello-world）
    ├── vitest.config.ts
    └── src/
        ├── index.tsx                   # views.registerView('sqllab.panels')
        ├── types.ts                    # API DTO 类型
        ├── api/
        │   ├── client.ts               # fetch 封装（CSRF/错误）
        │   └── client.test.ts
        ├── upload/
        │   ├── UploadManager.ts        # 队列/3 并发/分块/断点续传/进度
        │   └── UploadManager.test.ts
        └── components/
            ├── FileUpload.tsx          # 拖拽上传
            ├── FileUpload.test.tsx
            ├── DataPreview.tsx         # 100 行预览 + 列类型徽标
            ├── DataPreview.test.tsx
            ├── FileConfig.tsx          # 名称/描述/工作表/分隔符/编码
            ├── FileConfig.test.tsx
            ├── ColumnTypeEditor.tsx    # 列类型编辑 + JSON 导入
            ├── ColumnTypeEditor.test.tsx
            ├── FileList.tsx            # 文件管理（usage/过期/删除确认）
            ├── FileList.test.tsx
            ├── Notifications.tsx       # 过期提醒横幅
            └── Notifications.test.tsx
```

命名与接口锁定（后续任务严格沿用，不得改名）：

- 数据库表：`uploaded_files` `file_columns` `file_sheets` `upload_sessions` `column_type_change_logs` `file_delete_logs` `file_datasources`。
- 视图/表名规则：CSV 文件 → `file_<file_id 去横线>`；Excel 工作表 → `file_<file_id 去横线>_<sheet_index>`。函数 `query_engine.view_name(file_id, sheet_index=None)` 是唯一命名来源。
- 列类型字符串 ↔ SQLAlchemy/DuckDB 映射见 `config.py:TYPE_MAP / DUCKDB_TYPE_MAP`。
- API 基路径：`/extensions/my-org/file-db`（由 `@api` 装饰器按扩展 publisher/name 自动挂载，与 hello-world 一致）。

---

## Task 1: 项目脚手架与配置常量

**Files:**
- Create: `file-db/extension.json`
- Create: `file-db/backend/pyproject.toml`
- Create: `file-db/backend/requirement.txt`
- Create: `file-db/backend/requirement-dev.txt`
- Create: `file-db/backend/src/my_org/file_db/__init__.py`
- Create: `file-db/backend/src/my_org/file_db/config.py`
- Create: `file-db/backend/src/my_org/file_db/entrypoint.py`
- Test: `file-db/backend/tests/test_scaffold.py`

**Interfaces:**
- Consumes: 无（首个任务）。
- Produces: `config.py` 导出常量（后续所有任务引用）：`UPLOAD_MAX_CSV_BYTES` `UPLOAD_MAX_EXCEL_BYTES` `FILE_EXPIRY_DAYS` `PREVIEW_ROW_LIMIT` `UPLOAD_CHUNK_BYTES` `COLUMN_TYPES` `DUCKDB_TYPE_MAP` `SQLALCHEMY_TYPE_NAMES` `DELIMITERS` `ENCODINGS` `ALLOWED_EXTENSIONS` `FILENAME_MAX_LEN` `EXPIRY_WARNING_DAYS` `CLEANUP_THROTTLE_SECONDS` `VIEW_PREFIX` `STAGING_DIR_NAME`；包 `my_org.file_db` 可导入；`entrypoint.register_extension()` 完成方言注册。

- [ ] **Step 1: 安装开发/测试依赖**

```bash
/Users/ziskin/Development/superset-ex/.venv/bin/pip install pytest duckdb pandas openpyxl chardet
```

- [ ] **Step 2: 写失败测试**

`file-db/backend/tests/test_scaffold.py`:

```python
import my_org.file_db.config as cfg


def test_package_imports():
    import my_org.file_db  # noqa: F401


def test_limits_match_spec():
    assert cfg.UPLOAD_MAX_CSV_BYTES == 150 * 1024 * 1024
    assert cfg.UPLOAD_MAX_EXCEL_BYTES == 500 * 1024 * 1024
    assert cfg.FILE_EXPIRY_DAYS == 180
    assert cfg.PREVIEW_ROW_LIMIT == 100
    assert cfg.UPLOAD_CHUNK_BYTES == 8 * 1024 * 1024
    assert cfg.FILENAME_MAX_LEN == 255
    assert cfg.EXPIRY_WARNING_DAYS == 7


def test_type_maps_are_consistent():
    assert cfg.COLUMN_TYPES == {"string", "integer", "float", "datetime", "boolean"}
    assert set(cfg.DUCKDB_TYPE_MAP) == cfg.COLUMN_TYPES
    assert set(cfg.SQLALCHEMY_TYPE_NAMES) == cfg.COLUMN_TYPES


def test_upload_and_encoding_options():
    assert cfg.DELIMITERS == {",", ";", "\t", "|", " "}
    assert cfg.ENCODINGS == ["utf-8", "gbk", "gb2312", "latin-1"]
    assert cfg.ALLOWED_EXTENSIONS == {".csv", ".xls", ".xlsx"}


def test_entrypoint_registers_dialect():
    from my_org.file_db.entrypoint import register_extension
    from sqlalchemy.dialects import registry

    register_extension()
    assert "filedb" in registry.registry
```

- [ ] **Step 3: 运行测试确认失败**

Run: `python -m pytest tests/test_scaffold.py -v`（cwd = `file-db/backend`）
Expected: FAIL / ERROR，`ModuleNotFoundError: No module named 'my_org'`

- [ ] **Step 4: 写脚手架实现**

`file-db/extension.json`:

```json
{
  "publisher": "my-org",
  "name": "file-db",
  "displayName": "文件数据库",
  "version": "0.1.0",
  "license": "Apache-2.0",
  "permissions": []
}
```

`file-db/backend/pyproject.toml`:

```toml
[project]
name = "my_org-file_db"
version = "0.1.0"
license = "Apache-2.0"
dependencies = [
    "duckdb>=1.0.0",
    "pandas>=2.0.0",
    "openpyxl>=3.1.0",
    "chardet>=5.0.0",
]

[project.entry-points."sqlalchemy.dialects"]
filedb = "my_org.file_db.dialect:FileDBDialect"

[tool.apache_superset_extensions.build]
include = [
    "src/my_org/file_db/**/*.py",
]
exclude = []
```

`file-db/backend/requirement.txt`（构建镜像时 pip install 进宿主 venv）:

```
psycopg2-binary
duckdb>=1.0.0
pandas>=2.0.0
openpyxl>=3.1.0
chardet>=5.0.0
```

`file-db/backend/requirement-dev.txt`:

```
-r requirement.txt
pytest>=8.0.0
```

`file-db/backend/src/my_org/file_db/__init__.py`:

```python
"""Superset file-database engine extension (my-org/file-db)."""

__version__ = "0.1.0"
```

`file-db/backend/src/my_org/file_db/config.py`:

```python
"""Constants and type maps for the file-db extension.

Every limit and enumeration here comes from the design spec
(docs/superpowers/specs/2026-09-25-file-database-engine-design.md).
"""

UPLOAD_MAX_CSV_BYTES = 150 * 1024 * 1024
UPLOAD_MAX_EXCEL_BYTES = 500 * 1024 * 1024
FILE_EXPIRY_DAYS = 180
PREVIEW_ROW_LIMIT = 100
UPLOAD_CHUNK_BYTES = 8 * 1024 * 1024
FILENAME_MAX_LEN = 255
EXPIRY_WARNING_DAYS = 7
CLEANUP_THROTTLE_SECONDS = 3600

COLUMN_TYPES = {"string", "integer", "float", "datetime", "boolean"}

# user-facing type -> DuckDB type used in CREATE VIEW casts
DUCKDB_TYPE_MAP = {
    "string": "VARCHAR",
    "integer": "BIGINT",
    "float": "DOUBLE",
    "datetime": "TIMESTAMP",
    "boolean": "BOOLEAN",
}

# user-facing type -> SQLAlchemy type *name* returned by the dialect
SQLALCHEMY_TYPE_NAMES = {
    "string": "VARCHAR",
    "integer": "BIGINT",
    "float": "FLOAT",
    "datetime": "TIMESTAMP",
    "boolean": "BOOLEAN",
}

DELIMITERS = {",", ";", "\t", "|", " "}
ENCODINGS = ["utf-8", "gbk", "gb2312", "latin-1"]
ALLOWED_EXTENSIONS = {".csv", ".xls", ".xlsx"}

# encodings DuckDB read_csv understands natively; anything else is
# transcoded to UTF-8 at upload-complete time
DUCKDB_NATIVE_ENCODINGS = {"utf-8", "utf-16", "latin-1"}

VIEW_PREFIX = "file_"
STAGING_DIR_NAME = ".staging"
PARQUET_DIR_NAME = "parquet"

FILE_STATUS_ACTIVE = "active"
FILE_STATUS_EXPIRED = "expired"
FILE_STATUS_DELETED = "deleted"

UPLOAD_STATUS_UPLOADING = "uploading"
UPLOAD_STATUS_COMPLETED = "completed"
UPLOAD_STATUS_ABORTED = "aborted"

DELETE_REASON_USER = "user_deleted"
DELETE_REASON_ADMIN = "admin_deleted"
DELETE_REASON_EXPIRED = "expired"
```

`file-db/backend/src/my_org/file_db/entrypoint.py`:

```python
"""Extension entrypoint: registers REST APIs and the filedb dialect."""

from sqlalchemy.dialects import registry


def register_extension() -> None:
    # .supx deployments do not run `pip install`, so the pyproject
    # entry-point is not discovered at runtime. Register explicitly.
    registry.register("filedb", "my_org.file_db.dialect", "FileDBDialect")


register_extension()

# Importing API modules registers them with the Superset host via @api.
from .api import columns_api, datasources_api, files_api  # noqa: E402,F401

print("file-db extension registered")
```

注意：`entrypoint.py` 顶部的 `register_extension()` 先于 API import 执行；API 模块在 Task 16 才存在，因此本任务先写一个占位 `api` 包，`api/__init__.py` 为空文件，并把 entrypoint 的 API import 行注释掉，Task 16 时恢复：

```python
# from .api import columns_api, datasources_api, files_api  # noqa: E402,F401  (Task 16)
```

- [ ] **Step 5: 运行测试确认通过**

Run: `python -m pytest tests/test_scaffold.py -v`
Expected: 5 passed

- [ ] **Step 6: 提交**

```bash
git add file-db
git commit -m "feat: scaffold file-db extension package with config constants"
```

---

## Task 2: 数据库模型与会话工厂

**Files:**
- Create: `file-db/backend/src/my_org/file_db/db.py`
- Create: `file-db/backend/src/my_org/file_db/models.py`
- Test: `file-db/backend/tests/test_models.py`

**Interfaces:**
- Consumes: `config.py` 状态常量。
- Produces:
  - `db.py`: `Base`（declarative base）；`init_db(database_uri: str, echo: bool = False) -> None`（幂等，建 engine + scoped session + `create_all`）；`get_session() -> scoped_session`；`reset_db() -> None`（测试用）。
  - `models.py` ORM 类与字段（全部 `id: str = Column(String(36), primary_key=True)`，UUID 由调用方生成）：
    - `UploadedFile`: `created_by, filename, file_size, file_type, storage_path, upload_time, expiry_time, status, sheet_count, row_count, column_count, encoding, delimiter, created_at, updated_at`
    - `FileSheet`: `file_id(FK), sheet_name, sheet_index, row_count, column_count, is_selected`
    - `FileColumn`: `file_id(FK), sheet_id(FK nullable), column_name, column_type, column_format, column_order, is_nullable, sample_values(Text JSON), is_user_defined`
    - `UploadSession`: `created_by, filename, file_type, total_size, chunk_size, total_chunks, received_chunks(Text JSON), status, created_at, updated_at`
    - `ColumnTypeChangeLog`: `file_id, column_id, column_name, old_type, new_type, old_format, new_format, changed_by, changed_at`
    - `FileDeleteLog`: `file_id, filename, deleted_at, reason, deleted_by`
    - `FileDatasource`: `file_id, sheet_id(nullable), datasource_id(Integer), datasource_name, created_by, created_at`

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_models.py`:

```python
from datetime import datetime, timedelta

from my_org.file_db import db as dbmod
from my_org.file_db.config import (
    DELETE_REASON_USER,
    FILE_STATUS_ACTIVE,
    UPLOAD_STATUS_UPLOADING,
)
from my_org.file_db.models import (
    ColumnTypeChangeLog,
    FileColumn,
    FileDeleteLog,
    FileDatasource,
    FileSheet,
    UploadedFile,
    UploadSession,
)


def setup_function():
    dbmod.reset_db()
    dbmod.init_db("sqlite://")


def teardown_function():
    dbmod.reset_db()


def test_create_file_with_columns_and_sheets():
    session = dbmod.get_session()
    now = datetime(2026, 9, 25, 12, 0, 0)
    f = UploadedFile(
        id="f1",
        created_by="u1",
        filename="sales.csv",
        file_size=1024,
        file_type="csv",
        storage_path="u1/f1/sales.csv",
        upload_time=now,
        expiry_time=now + timedelta(days=180),
        status=FILE_STATUS_ACTIVE,
        sheet_count=1,
        column_count=2,
        encoding="utf-8",
        delimiter=",",
    )
    session.add(f)
    session.add(
        FileColumn(
            id="c1",
            file_id="f1",
            sheet_id=None,
            column_name="amount",
            column_type="float",
            column_order=0,
            is_nullable=True,
            sample_values='["1.5", "2.0"]',
            is_user_defined=False,
        )
    )
    session.add(
        FileSheet(
            id="s1",
            file_id="f1",
            sheet_name="Sheet1",
            sheet_index=0,
            row_count=10,
            column_count=2,
            is_selected=True,
        )
    )
    session.commit()

    loaded = session.get(UploadedFile, "f1")
    assert loaded.filename == "sales.csv"
    assert loaded.columns[0].column_name == "amount"
    assert loaded.sheets[0].sheet_name == "Sheet1"


def test_upload_session_roundtrip():
    session = dbmod.get_session()
    session.add(
        UploadSession(
            id="up1",
            created_by="u1",
            filename="big.xlsx",
            file_type="excel",
            total_size=100,
            chunk_size=10,
            total_chunks=10,
            received_chunks="[0, 1]",
            status=UPLOAD_STATUS_UPLOADING,
        )
    )
    session.commit()
    up = session.get(UploadSession, "up1")
    assert up.received_chunks == "[0, 1]"
    assert up.status == "uploading"


def test_log_tables_store_forever():
    session = dbmod.get_session()
    session.add(
        ColumnTypeChangeLog(
            id="l1",
            file_id="f1",
            column_id="c1",
            column_name="amount",
            old_type="string",
            new_type="float",
            changed_by="u1",
            changed_at=datetime(2026, 9, 25),
        )
    )
    session.add(
        FileDeleteLog(
            id="d1",
            file_id="f1",
            filename="sales.csv",
            deleted_at=datetime(2026, 9, 25),
            reason=DELETE_REASON_USER,
            deleted_by="u1",
        )
    )
    session.add(
        FileDatasource(
            id="ds1",
            file_id="f1",
            sheet_id=None,
            datasource_id=42,
            datasource_name="Sales",
            created_by="u1",
        )
    )
    session.commit()
    assert session.query(ColumnTypeChangeLog).count() == 1
    assert session.query(FileDeleteLog).one().reason == "user_deleted"
    assert session.query(FileDatasource).one().datasource_id == 42


def test_cascade_delete_columns_and_sheets():
    session = dbmod.get_session()
    f = UploadedFile(
        id="f2",
        created_by="u1",
        filename="a.csv",
        file_size=1,
        file_type="csv",
        storage_path="u1/f2/a.csv",
        upload_time=datetime(2026, 9, 25),
        expiry_time=datetime(2027, 3, 25),
        status=FILE_STATUS_ACTIVE,
    )
    session.add(f)
    session.add(
        FileColumn(
            id="c2",
            file_id="f2",
            column_name="x",
            column_type="string",
            column_order=0,
            sample_values="[]",
        )
    )
    session.commit()
    session.delete(f)
    session.commit()
    assert session.query(FileColumn).count() == 0
```

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_models.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'my_org.file_db.db'`

- [ ] **Step 3: 写实现**

`file-db/backend/src/my_org/file_db/db.py`:

```python
"""Engine/session factory for extension metadata tables.

The extension owns its own declarative Base but stores tables in the
Superset PostgreSQL database (same SQLALCHEMY_DATABASE_URI).
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, scoped_session, sessionmaker

Base = declarative_base()

_engine = None
_session_factory = None


def init_db(database_uri: str, echo: bool = False) -> None:
    global _engine, _session_factory
    if _session_factory is not None:
        return
    connect_args = {}
    if database_uri.startswith("sqlite"):
        connect_args["check_same_thread"] = False
    _engine = create_engine(database_uri, echo=echo, connect_args=connect_args)
    _session_factory = scoped_session(sessionmaker(bind=_engine))
    from . import models  # noqa: F401  register mappers

    Base.metadata.create_all(_engine)


def get_session():
    if _session_factory is None:
        raise RuntimeError("db.init_db() must be called before get_session()")
    return _session_factory


def reset_db() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None
```

`file-db/backend/src/my_org/file_db/models.py`:

```python
"""ORM models for file metadata, upload sessions and audit logs.

Audit tables (column_type_change_logs, file_delete_logs) are append-only
and never purged, per spec 5.9/5.12.
"""

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import relationship

from .db import Base


def _uuid_pk():
    return Column(String(36), primary_key=True)


class UploadedFile(Base):
    __tablename__ = "uploaded_files"

    id = _uuid_pk()
    created_by = Column(String(36), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_size = Column(BigInteger, nullable=False)
    file_type = Column(String(16), nullable=False)  # 'csv' | 'excel'
    storage_path = Column(String(500), nullable=False)
    upload_time = Column(DateTime, nullable=False)
    expiry_time = Column(DateTime, nullable=False)
    status = Column(String(16), nullable=False, default="active")
    sheet_count = Column(Integer, nullable=False, default=1)
    row_count = Column(BigInteger, nullable=True)
    column_count = Column(Integer, nullable=True)
    encoding = Column(String(32), nullable=True)
    delimiter = Column(String(8), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    columns = relationship(
        "FileColumn",
        back_populates="file",
        cascade="all, delete-orphan",
        order_by="FileColumn.column_order",
    )
    sheets = relationship(
        "FileSheet",
        back_populates="file",
        cascade="all, delete-orphan",
        order_by="FileSheet.sheet_index",
    )


class FileSheet(Base):
    __tablename__ = "file_sheets"

    id = _uuid_pk()
    file_id = Column(String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"), nullable=False, index=True)
    sheet_name = Column(String(255), nullable=False)
    sheet_index = Column(Integer, nullable=False)
    row_count = Column(BigInteger, nullable=True)
    column_count = Column(Integer, nullable=True)
    is_selected = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False)

    file = relationship("UploadedFile", back_populates="sheets")


class FileColumn(Base):
    __tablename__ = "file_columns"

    id = _uuid_pk()
    file_id = Column(String(36), ForeignKey("uploaded_files.id", ondelete="CASCADE"), nullable=False, index=True)
    sheet_id = Column(String(36), ForeignKey("file_sheets.id", ondelete="CASCADE"), nullable=True, index=True)
    column_name = Column(String(255), nullable=False)
    column_type = Column(String(50), nullable=False)
    column_format = Column(String(100), nullable=True)
    column_order = Column(Integer, nullable=False)
    is_nullable = Column(Boolean, nullable=False, default=True)
    sample_values = Column(Text, nullable=False, default="[]")
    is_user_defined = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)

    file = relationship("UploadedFile", back_populates="columns")


class UploadSession(Base):
    __tablename__ = "upload_sessions"

    id = _uuid_pk()
    created_by = Column(String(36), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    file_type = Column(String(16), nullable=False)
    total_size = Column(BigInteger, nullable=False)
    chunk_size = Column(Integer, nullable=False)
    total_chunks = Column(Integer, nullable=False)
    received_chunks = Column(Text, nullable=False, default="[]")
    status = Column(String(16), nullable=False, default="uploading")
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(DateTime, nullable=False)


class ColumnTypeChangeLog(Base):
    __tablename__ = "column_type_change_logs"

    id = _uuid_pk()
    file_id = Column(String(36), nullable=False, index=True)
    column_id = Column(String(36), nullable=False)
    column_name = Column(String(255), nullable=False)
    old_type = Column(String(50), nullable=False)
    new_type = Column(String(50), nullable=False)
    old_format = Column(String(100), nullable=True)
    new_format = Column(String(100), nullable=True)
    changed_by = Column(String(36), nullable=False)
    changed_at = Column(DateTime, nullable=False)


class FileDeleteLog(Base):
    __tablename__ = "file_delete_logs"

    id = _uuid_pk()
    file_id = Column(String(36), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    deleted_at = Column(DateTime, nullable=False)
    reason = Column(String(32), nullable=False)
    deleted_by = Column(String(36), nullable=False)


class FileDatasource(Base):
    __tablename__ = "file_datasources"

    id = _uuid_pk()
    file_id = Column(String(36), nullable=False, index=True)
    sheet_id = Column(String(36), nullable=True)
    datasource_id = Column(Integer, nullable=False)
    datasource_name = Column(String(255), nullable=False)
    created_by = Column(String(36), nullable=False)
    created_at = Column(DateTime, nullable=False)
```

说明：`sample_values`/`received_chunks` 用 `Text` 存 JSON 字符串（SQLite 测试兼容）；服务层用 `json.loads/dumps` 编解码。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_models.py -v`
Expected: 4 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/db.py backend/src/my_org/file_db/models.py backend/tests/test_models.py
git commit -m "feat: add metadata ORM models and session factory"
```

---

## Task 3: 存储层（StorageBackend + LocalStorageBackend）

**Files:**
- Modify: `file-db/backend/src/my_org/file_db/config.py`（新增 `UPLOAD_ROOT`）
- Create: `file-db/backend/src/my_org/file_db/storage/__init__.py`
- Create: `file-db/backend/src/my_org/file_db/storage/base.py`
- Create: `file-db/backend/src/my_org/file_db/storage/local.py`
- Test: `file-db/backend/tests/test_storage.py`

**Interfaces:**
- Consumes: `config.py` 新增 `UPLOAD_ROOT = os.environ.get("FILE_DB_UPLOAD_ROOT", "/data/uploads")`（spec 5.2：Admin 配置大目录）；已有限制常量。
- Produces:
  - `storage/base.py`：
    ```python
    class StorageBackend(ABC):
        def save_file(self, file_data: BinaryIO, user_id: str, file_id: str, filename: str) -> str: ...  # 返回相对 storage_path
        def get_file_path(self, storage_path: str) -> str: ...
        def delete_file(self, storage_path: str) -> bool: ...
        def file_exists(self, storage_path: str) -> bool: ...
        def staging_dir(self, user_id: str, upload_id: str) -> str: ...   # 确保并返回分块暂存目录
        def delete_staging(self, user_id: str, upload_id: str) -> bool: ...
    ```
  - `storage/local.py`：`class LocalStorageBackend(StorageBackend)`，`__init__(self, base_path: str = config.UPLOAD_ROOT)`，构造时 `mkdir(parents=True, exist_ok=True)`。
  - 磁盘布局：正式文件 `<base>/<user_id>/<file_id>/<filename>`（storage_path 即其相对路径）；分块暂存 `<base>/<config.STAGING_DIR_NAME>/<user_id>/<upload_id>/<index:06d>.part`。
  - 安全（必须实现）：`get_file_path` / `delete_file` / `file_exists` 对 `storage_path` 先 `Path.resolve()` 再校验仍在 `base_path.resolve()` 之内，越界抛 `ValueError`（防目录穿越）。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_storage.py` 关键用例（用 `tmp_path` 作 base_path）：
- `test_save_file_layout_and_roundtrip`：save_file 返回 `u1/f1/a.csv`，get_file_path 读回内容一致，文件落在 `<base>/u1/f1/a.csv`。
- `test_delete_file_and_dir`：delete_file 删单文件返回 True；删不存在路径返回 False。
- `test_file_exists`：存在/不存在两态。
- `test_path_traversal_rejected`：`get_file_path("../../etc/passwd")` 与 `delete_file("u1/../../x")` 均抛 `ValueError`。
- `test_staging_dir_lifecycle`：staging_dir 创建 `<base>/.staging/u1/up1/`，delete_staging 清空并返回 True。
- `test_user_isolation`：不同 user_id/file_id 落不同子目录，互不覆盖。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_storage.py -v`（cwd = `file-db/backend`）
Expected: FAIL，`ModuleNotFoundError: No module named 'my_org.file_db.storage'`

- [ ] **Step 3: 写实现**

`base.py` 按 Interfaces 落 ABC；`local.py` 要点：
- `save_file`：`user_dir = base/user_id/file_id`（mkdir）→ `shutil.copyfileobj(file_data, f)` → 返回 `str(Path(user_id) / file_id / filename)`（POSIX 分隔）。
- `delete_file`：解析校验后，文件 `unlink()`，目录 `shutil.rmtree()`。
- `_resolve_safe(storage_path)` 私有助手统一做穿越校验，三个查询方法共用。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_storage.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/config.py backend/src/my_org/file_db/storage backend/tests/test_storage.py
git commit -m "feat: add storage backend abstraction with local implementation"
```

---

## Task 4: schema 推断与 CSV 解析器

**Files:**
- Create: `file-db/backend/src/my_org/file_db/parsers/__init__.py`
- Create: `file-db/backend/src/my_org/file_db/parsers/schema.py`
- Create: `file-db/backend/src/my_org/file_db/parsers/csv_parser.py`
- Test: `file-db/backend/tests/test_csv_parser.py`

**Interfaces:**
- Consumes: `config.py` 的 `DELIMITERS` `ENCODINGS` `DUCKDB_NATIVE_ENCODINGS` `COLUMN_TYPES`。
- Produces `parsers/schema.py`：
  ```python
  @dataclass
  class ColumnSchema:
      name: str; column_type: str; column_format: str | None = None
      is_nullable: bool = True; sample_values: list[str] = field(default_factory=list)

  @dataclass
  class SheetSchema:
      name: str; index: int; row_count: int | None = None; column_count: int | None = None

  @dataclass
  class FileSchema:
      columns: list[ColumnSchema]; sheets: list[SheetSchema]; row_count: int | None = None

  def infer_column_type(values: Sequence[str]) -> tuple[str, str | None]: ...
  ```
  推断规则（对前 200 个非空值按序尝试）：boolean（`true/false/yes/no/t/f` 大小写不敏感）→ integer（`int()`）→ float（`float()`）→ datetime（依次尝试 `%Y-%m-%d`、`%Y/%m/%d`、`%Y-%m-%d %H:%M:%S`、`%Y-%m-%dT%H:%M:%S`，命中返回该格式串）→ string；任一值失败即降级 string。有空值则 `is_nullable=True`；`sample_values` 取前 3 个非空值。
- Produces `parsers/csv_parser.py`：
  ```python
  def detect_encoding(path: str) -> str
  def detect_delimiter(path: str, encoding: str) -> str
  def parse_schema(path: str, encoding: str, delimiter: str) -> FileSchema
  def count_rows(path: str, encoding: str, delimiter: str) -> int
  def read_rows(path: str, encoding: str, delimiter: str, limit: int = 100, offset: int = 0) -> list[list[str | None]]
  def transcode_to_utf8(path: str, encoding: str) -> str
  ```
  - `detect_encoding`：chardet 检测，结果归一化进 `ENCODINGS`（`gb2312`→`gbk`），未知回退 `utf-8`。
  - `detect_delimiter`：先 `csv.Sniffer().sniff`，失败对前 10 行对 `, ; \t |` 与空格计数取最高。
  - `parse_schema`：读首行表头 + 抽样窗口推断（列名重复时追加 `_2` 后缀保证唯一）。
  - `transcode_to_utf8`：以源编码流式转码写 `<path>.utf8` 并返回新路径（供 upload complete 时替换）。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_csv_parser.py` 关键用例（样本在 `tmp_path` 动态生成，含 GBK 编码文件，不入库）：
- `test_detect_encoding_utf8_and_gbk`：gbk 样本检出 `gbk`；gb2312 内容归一化为 `gbk`。
- `test_detect_delimiters`：`,` `;` `\t` `|` 空格五种分隔文件各检出正确值。
- `test_infer_column_types`：int/float/bool/datetime（`2026-09-25` 返回 `%Y-%m-%d`）/string/混合值降级 string/含空值 `is_nullable=True`。
- `test_parse_schema_samples`：列名唯一化、每列 3 个 sample_values。
- `test_count_and_read_rows`：count_rows 正确；read_rows limit/offset/越界（返回空列表）。
- `test_transcode_to_utf8`：GBK 文件转码后按 utf-8 读取内容一致。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_csv_parser.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'my_org.file_db.parsers'`

- [ ] **Step 3: 写实现**

按 Interfaces 实现；难点提示：
- datetime 推断对每个候选格式尝试解析窗口内全部值，全部命中才返回该格式。
- `count_rows` 用 `csv.reader` 流式计数（含表头则减 1），不要 `readlines()`（大文件内存）。
- 编码读取统一 `open(path, encoding=..., newline="")`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_csv_parser.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/parsers backend/tests/test_csv_parser.py
git commit -m "feat: add schema inference and CSV parser"
```

---

## Task 5: Excel 解析器

**Files:**
- Modify: `file-db/backend/pyproject.toml`、`file-db/backend/requirement.txt`、`file-db/backend/requirement-dev.txt`（新增 `xlrd>=2.0`，.xls 支持）
- Create: `file-db/backend/src/my_org/file_db/parsers/excel_parser.py`
- Test: `file-db/backend/tests/test_excel_parser.py`

**Interfaces:**
- Consumes: `parsers/schema.py`（`ColumnSchema`/`SheetSchema`/`FileSchema`/`infer_column_type`）。
- Produces `parsers/excel_parser.py`：
  ```python
  def list_sheets(path: str) -> list[SheetSchema]
  def parse_schema(path: str, sheet: str | int) -> FileSchema
  def count_rows(path: str, sheet: str | int) -> int
  def read_rows(path: str, sheet: str | int, limit: int = 100, offset: int = 0) -> list[list[Any]]
  def to_parquet(path: str, sheet: str | int, dest: str) -> str
  ```
  - `.xlsx` 用 openpyxl（`read_only=True`），`.xls` 由 pandas 自动选 xlrd engine。
  - `to_parquet`：`pd.read_excel(path, sheet_name=sheet)` → `df.to_parquet(dest)`（dest 父目录自动创建），返回 dest。
  - 空单元格统一转 `None`；日期单元格转 `str`（isoformat）后进 `sample_values`。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_excel_parser.py` 关键用例（openpyxl/pandas 动态生成 xlsx）：
- `test_list_sheets`：3 个工作表（含中文名）→ 名称/index/行列数正确。
- `test_parse_schema_per_sheet`：每表独立 schema，类型推断与 CSV 相同。
- `test_read_rows_limit`：read_rows 返回 100 行上限、列数正确、空单元格为 None。
- `test_to_parquet_roundtrip`：to_parquet 后 `pd.read_parquet` 与 `pd.read_excel` 等值，dest 目录自动创建。
- `test_xls_smoke`：`.xls` 文件 list_sheets/read_rows 可用（xlrd）。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_excel_parser.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

先装依赖：`/Users/ziskin/Development/superset-ex/.venv/bin/pip install xlrd>=2.0`，并同步三个依赖文件。实现按 Interfaces；`list_sheets` 用 `pd.ExcelFile(path).sheet_names` + 逐表读取尺寸（openpyxl `max_row/max_column`）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_excel_parser.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add backend/pyproject.toml backend/requirement.txt backend/requirement-dev.txt backend/src/my_org/file_db/parsers backend/tests/test_excel_parser.py
git commit -m "feat: add Excel parser with sheet schema and parquet export"
```

---

## Task 6: MetadataManager（文件/列/工作表登记）

**Files:**
- Create: `file-db/backend/src/my_org/file_db/metadata.py`
- Test: `file-db/backend/tests/test_metadata.py`

**Interfaces:**
- Consumes: `db.py` 会话工厂、`models.py` ORM、`config.py` 状态常量、`parsers/schema.py` 数据类。
- Produces `metadata.py`：
  ```python
  class MetadataManager:
      def __init__(self, session): ...
      def create_file_record(self, *, created_by, filename, file_size, file_type, storage_path,
                             encoding=None, delimiter=None, sheet_count=1, file_id=None) -> str
      def create_sheets(self, file_id: str, sheets: list[SheetSchema]) -> list[str]
      def create_columns(self, file_id: str, columns: list[ColumnSchema], sheet_id: str | None = None) -> list[str]
      def get_file(self, file_id: str) -> UploadedFile | None
      def get_user_files(self, user_id: str, status: str = FILE_STATUS_ACTIVE) -> list[UploadedFile]
      def update_file_status(self, file_id: str, status: str) -> bool
      def get_columns(self, file_id: str, sheet_id: str | None = None) -> list[FileColumn]
      def delete_file_record(self, file_id: str) -> bool
  ```
  要点：`file_id` 缺省 `str(uuid.uuid4())`；`upload_time = datetime.utcnow()`，`expiry_time = upload_time + timedelta(days=FILE_EXPIRY_DAYS)`（180 天）；`sample_values` 用 `json.dumps`；`get_user_files` 按 `upload_time` 倒序；`delete_file_record` 走 ORM cascade 删 columns/sheets。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_metadata.py` 关键用例（sqlite 内存库，setup/teardown 调 `dbmod.reset_db/init_db`）：
- `test_create_and_get_file`：create→get 回环，字段一致，file_id 为 UUID 串。
- `test_expiry_is_180_days`：`expiry_time - upload_time == 180 天`。
- `test_columns_and_sheets_order`：create_columns/create_sheets 后按 column_order/sheet_index 排序返回，sample_values JSON 可解。
- `test_user_files_filter`：仅返回本人 active 文件，按上传时间倒序；status 过滤生效。
- `test_delete_file_record_cascades`：删除后 columns/sheets 记录消失。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_metadata.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'my_org.file_db.metadata'`

- [ ] **Step 3: 写实现**

按 Interfaces 实现；每个写方法 `session.commit()`，异常时 `session.rollback()` 后抛出。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_metadata.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/metadata.py backend/tests/test_metadata.py
git commit -m "feat: add metadata manager for files, columns and sheets"
```

---

## Task 7: 列类型管理与修改历史

**Files:**
- Modify: `file-db/backend/src/my_org/file_db/metadata.py`
- Test: `file-db/backend/tests/test_column_history.py`

**Interfaces:**
- Consumes: `config.COLUMN_TYPES`、`models.ColumnTypeChangeLog`。
- Produces（`MetadataManager` 新增方法）：
  ```python
  def update_column_type(self, file_id: str, column_id: str, column_type: str,
                         column_format: str | None = None, changed_by: str | None = None) -> bool
  def get_column_types(self, file_id: str) -> list[dict]
      # [{id, name, type, format, is_user_defined, sample_values}]
  def list_column_change_logs(self, file_id: str) -> list[ColumnTypeChangeLog]
  def import_column_config(self, file_id: str, config: dict, changed_by: str | None = None) -> int
  ```
  规则（spec 5.9）：
  - `column_type` 必须 ∈ `COLUMN_TYPES`，否则 `ValueError`；`column_format` 仅 datetime 使用（strptime 格式，如 `%Y-%m-%d`），其他类型强制置 None。
  - 每次变更写一条 `ColumnTypeChangeLog`（old/new type 与 format、changed_by、changed_at），`is_user_defined=True`，`updated_at` 刷新；历史**永久保留**（不提供删除方法）。
  - `import_column_config` 接收 `{"columns": [{"name": "...", "type": "...", "format": "..."}]}`；先整体校验（列名必须存在、类型合法、格式合法），**任一非法整体拒绝抛 `ValueError` 且不写任何变更**；合法则逐列应用并各自写历史，返回应用列数。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_column_history.py` 关键用例：
- `test_update_column_type_writes_log`：old/new type+format 正确、`is_user_defined=True`。
- `test_history_accumulates`：连续 3 次变更，`list_column_change_logs` 3 条按时间升序。
- `test_invalid_type_rejected`：`column_type="json"` 抛 `ValueError`，无日志写入。
- `test_datetime_format_rules`：datetime 带/不带格式均可；非 datetime 传格式被忽略（存 None）。
- `test_import_config_applies_all`：合法 JSON 批量应用，返回列数，历史逐列写入。
- `test_import_config_rejects_wholesale`：含一条非法（未知列名/非法类型）→ 抛 `ValueError`，**无任何列被修改**。
- `test_get_column_types_shape`：返回 dict 字段齐全、sample_values 可解。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_column_history.py -v`
Expected: FAIL（方法不存在 / NotImplementedError）

- [ ] **Step 3: 写实现**

按 Interfaces 实现；`import_column_config` 先做纯校验循环（收集目标列与错误），全部通过后才进入写循环（保证原子性语义）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_column_history.py -v`
Expected: 7 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/metadata.py backend/tests/test_column_history.py
git commit -m "feat: add column type management with permanent change history"
```

---

## Task 8: UploadManager（分块上传、校验与登记）

**Files:**
- Create: `file-db/backend/src/my_org/file_db/upload.py`
- Test: `file-db/backend/tests/test_upload.py`

**Interfaces:**
- Consumes: `storage.base.StorageBackend`、`metadata.MetadataManager`、`parsers.csv_parser`（detect/transcode）、`config.py` 限制常量。
- Produces `upload.py`：
  ```python
  class UploadManager:
      def __init__(self, storage: StorageBackend, metadata: MetadataManager): ...
      def init_upload(self, created_by: str, filename: str, file_type: str, total_size: int,
                      chunk_size: int = UPLOAD_CHUNK_BYTES) -> str          # -> upload_id
      def add_chunk(self, upload_id: str, chunk_index: int, data: bytes) -> dict
      def get_status(self, upload_id: str) -> dict                           # {received_chunks, total_chunks, total_size, status}
      def complete_upload(self, upload_id: str) -> str                       # -> file_id
      def abort_upload(self, upload_id: str) -> bool
  ```
  校验规则（init 时全部前置，违规抛 `ValueError`）：
  - 扩展名 ∈ `ALLOWED_EXTENSIONS` 且与 `file_type` 一致（`.csv`→`csv`；`.xls/.xlsx`→`excel`）。
  - `filename` ≤ `FILENAME_MAX_LEN` 且匹配 `^[A-Za-z0-9\u4e00-\u9fa5 ._\-()]+$`。
  - `total_size` ≤ 对应上限（csv 150MB / excel 500MB）且 > 0。
  - `total_chunks = ceil(total_size / chunk_size)`；chunk_size 固定 `UPLOAD_CHUNK_BYTES`（8MB）。
  行为：
  - `add_chunk`：`0 ≤ chunk_index < total_chunks`；幂等（重复块覆盖不重复计数）；写 `storage.staging_dir(...)/<index:06d>.part`；`received_chunks` JSON 更新。
  - `complete_upload`：缺块抛 `ValueError`（message 含缺失索引）→ 按序拼接 → `storage.save_file` → CSV：`detect_encoding`，不在 `DUCKDB_NATIVE_ENCODINGS` 则 `transcode_to_utf8` 并替换存储文件、encoding 记录为 `utf-8`（原编码保留在 `encoding` 字段语义为"当前存储编码"）→ `detect_delimiter` 供预览默认值 → `metadata.create_file_record` → `delete_staging` + 会话置 completed。
  - `abort_upload`：删 staging + 会话置 aborted。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_upload.py` 关键用例（tmp_path 真存储 + 内存 sqlite 元数据）：
- `test_init_validation_matrix`：坏扩展名/类型不符/超大小/空文件/超长文件名/非法字符各抛 `ValueError`。
- `test_chunk_order_and_idempotency`：乱序块、重复块均接受，status 中 received 去重计数正确。
- `test_complete_missing_chunk_fails`：缺块 complete 抛错且列出缺失索引。
- `test_complete_creates_file_record`：complete 后文件落盘、size/type/encoding/delimiter 记录正确、staging 清空。
- `test_gbk_transcoded`：GBK CSV complete 后存储文件为 UTF-8，行内容一致。
- `test_abort_cleans_up`：abort 后 staging 与会话状态正确。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_upload.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'my_org.file_db.upload'`

- [ ] **Step 3: 写实现**

按 Interfaces 实现；拼接用 `shutil.copyfileobj` 逐块写目标临时文件再 `os.replace` 原子落盘。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_upload.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/upload.py backend/tests/test_upload.py
git commit -m "feat: add resumable chunked upload manager"
```

---

## Task 9: FileQueryEngine（共享 DuckDB 连接 + 每文件视图）

**Files:**
- Create: `file-db/backend/src/my_org/file_db/query_engine.py`
- Test: `file-db/backend/tests/test_query_engine.py`

**Interfaces:**
- Consumes: `storage`、`metadata`、`parsers.excel_parser.to_parquet`、`config.DUCKDB_TYPE_MAP`。
- Produces `query_engine.py`：
  ```python
  def view_name(file_id: str, sheet_index: int | None = None) -> str   # 唯一命名来源
      # CSV: file_<file_id 去横线>；Excel 工作表: file_<file_id 去横线>_<sheet_index>

  class FileQueryEngine:
      def __init__(self, storage, metadata, parquet_dir: str | None = None)
      def get_connection(self) -> duckdb.DuckDBPyConnection          # 进程内共享 :memory:，RLock 保护
      def ensure_view(self, file_id: str, sheet_index: int | None = None) -> str
      def ensure_view_by_name(self, name: str) -> str                 # 供方言 SQL 文本路由
      def invalidate(self, file_id: str) -> None                      # DROP 该文件全部视图（列变更后重建）
      def query(self, file_id: str, sql: str, sheet_index: int | None = None) -> pd.DataFrame
      def preview(self, file_id: str, sheet_index: int | None = None, limit: int = PREVIEW_ROW_LIMIT) -> dict
      def close(self) -> None
  ```
  **设计决策（覆盖 spec 5.14"每文件独立连接"）**：进程内共享一个 `:memory:` DuckDB 连接，每个文件/工作表注册一个 VIEW。理由：Superset Dataset 与 SQL Lab 的 SQL 是纯文本（`FROM file_xxx`），需要跨文件 JOIN；视图彼此隔离文件来源，`invalidate`/DROP 即可热更新。文件删除时 `invalidate`。
  视图 DDL：
  - CSV：`CREATE OR REPLACE VIEW {v} AS SELECT {casts} FROM read_csv_auto('<path>', delim='<delim>', header=true, all_varchar=true)`。
  - Excel：惰性 `to_parquet` 缓存至 `<parquet_dir>/<file_id>/<sheet_index>.parquet`（存在即复用）→ `read_parquet('<path>')`。
  - `{casts}` 生成规则：用户定义列 → `TRY_CAST("{col}" AS {DUCKDB_TYPE_MAP[type]}) AS "{col}"`；datetime 带 format → `TRY_CAST(strptime("{col}", '<fmt>') AS TIMESTAMP) AS "{col}"`；未定义列 → `"{col}"`。
  `preview` 返回 `{"columns": [{"name","type","format"}], "rows": [[...]], "totalRows": n}`（Timestamp→isoformat 字符串、NaN→None，保证 JSON 可序列化）。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_query_engine.py` 关键用例：
- `test_view_name_shape`：CSV/Excel 视图名符合锁定规则、去横线、唯一。
- `test_csv_view_query`：注册后 `SELECT * FROM <view>` 返回全量行。
- `test_user_type_cast`：列类型改 integer 后 `"42"` 查出 42；坏值变 NULL（TRY_CAST 不炸）。
- `test_datetime_strptime`：format `%Y-%m-%d` 的日期列可按 TIMESTAMP 过滤比较。
- `test_excel_sheet_views`：双 sheet 两个视图互不串数据；parquet 缓存二次调用不重转（文件 mtime/调用计数断言）。
- `test_preview_shape`：rows ≤ limit、totalRows 为全量、columns 含 type。
- `test_invalidate_rebuilds`：改列类型后 invalidate → ensure_view 用新 casts。
- `test_cross_view_join`：两个文件视图 JOIN 查询成功。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_query_engine.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

按 Interfaces 实现；`ensure_view_by_name` 用正则解析视图名（`file_<32hex>(_\d+)?`）反查 file_id/sheet_index。所有 duckdb 执行进 `with self._lock:`。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_query_engine.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/query_engine.py backend/tests/test_query_engine.py
git commit -m "feat: add DuckDB query engine with per-file views"
```

---

## Task 10: SQLAlchemy `filedb` 方言

**Files:**
- Create: `file-db/backend/src/my_org/file_db/dialect.py`
- Test: `file-db/backend/tests/test_dialect.py`

**Interfaces:**
- Consumes: `query_engine.view_name/ensure_view_by_name`（经工厂注入）、`metadata`（列元数据）、`config.SQLALCHEMY_TYPE_NAMES`。
- Produces `dialect.py`：
  ```python
  class FileDBDialect(Dialect):
      name = "filedb"; driver = "duckdb"
      @classmethod
      def import_dbapi(cls): ...                    # 返回 DBAPI shim：FileDBModule
      def create_connect_args(self, url): ...       # filedb:// 可带 ?echo=1
      def get_table_names(self, connection, schema=None, **kw): ...
      def get_view_names(self, connection, schema=None, **kw): ...
      def get_columns(self, connection, table_name, schema=None, **kw): ...
      def get_schema_names(self, connection, **kw): ...   # ["main"]
      def has_table(self, connection, table_name, schema=None, **kw): ...

  def set_engine_factory(fn) -> None                # entrypoint/测试注入 FileQueryEngine 工厂
  ```
  DBAPI shim（同文件内）：`FileDBModule`（`paramstyle="qmark"`、`apilevel="2.0"`、`connect(**kwargs) -> FileDBConnection`）→ `FileDBCursor.execute(sql, params=None)` 先用正则 `\b(file_[0-9a-f]{32}(?:_\d+)?)\b` 提取视图名逐个 `ensure_view_by_name`，再交共享 duckdb 连接执行；`fetchone/fetchall/fetchmany/description/rowcount/close` 透传。
  - `get_table_names/get_view_names`：`metadata` 中 `status=active` 的文件按 sheet 数展开视图名（CSV 1 个/文件，Excel 每选中 sheet 1 个）。
  - `get_columns`：元数据列 → `{"name", "type": <SQLAlchemy 类型实例>, "nullable", "default": None}`，类型名按 `SQLALCHEMY_TYPE_NAMES`。
  - 方言**不**直接 new FileQueryEngine：模块级 `set_engine_factory(fn)` 注入（entrypoint 默认注入真实工厂；测试注入 fake）。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_dialect.py` 关键用例（fake metadata + fake engine 工厂）：
- `test_import_dbapi_module`：`import_dbapi()` 有 `connect`、`paramstyle="qmark"`。
- `test_create_connect_args`：`filedb://` URL 解析出 kwargs。
- `test_table_names_and_columns`：active 文件展开视图名；get_columns 返回类型实例与 nullable。
- `test_execute_routes_to_engine`：`SELECT * FROM file_<hex>` 触发 `ensure_view_by_name` 并 fetchall 返回行。
- `test_join_two_views`：JOIN 语句两视图均被 ensure。
- `test_has_table`：存在/不存在两态。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_dialect.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

按 Interfaces 实现；SQLAlchemy 1.4 兼容（`import_dbapi` classmethod + `dbapi()` 兼容别名）；`initialize`/`do_execute` 等未用到的钩子不实现。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_dialect.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/dialect.py backend/tests/test_dialect.py
git commit -m "feat: add filedb SQLAlchemy dialect with DBAPI shim"
```

---

## Task 11: 宿主集成（host_db）与权限（permissions）

**Files:**
- Create: `file-db/backend/src/my_org/file_db/host_db.py`
- Create: `file-db/backend/src/my_org/file_db/permissions.py`
- Test: `file-db/backend/tests/test_permissions.py`

**Interfaces:**
- Consumes: 运行时宿主 `superset.*`（**惰性解析，模块顶层零 import**——venv 无 superset 包，违反即测试无法运行）。
- Produces `host_db.py`：
  ```python
  def get_metadata_db_uri() -> str                  # 宿主 SQLALCHEMY_DATABASE_URI，缺省读 env FILE_DB_METADATA_URI
  def get_superset_session_factory()                # 宿主 session 工厂
  def resolve_model(name: str)                      # 'SqlaTable' | 'Database' | 'Slice'，importlib 惰性
  def set_injectables(**kwargs)                     # 测试注入：metadata_uri / session_factory / models
  ```
  解析目标（找不到抛 `RuntimeError` 而非 ImportError）：`superset.connectors.sqla.models.SqlaTable`、`superset.models.core.Database`、`superset.models.slice.Slice`。
- Produces `permissions.py`：
  ```python
  def current_user()                                # flask.g.user，未登录抛 PermissionError
  def current_user_id() -> str
  def is_admin(user=None) -> bool                   # 角色名含 'Admin'
  def can_create_datasource(user=None) -> bool      # 'can_write on Dataset' 或 Admin
  def check_file_owner(file_record, user=None) -> None   # 非 owner/admin 抛 PermissionError
  ```
  权限原则（spec 6）：只复用 Superset 权限体系，无自定义角色。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_permissions.py` 关键用例（fake user/roles 注入 + `set_injectables`）：
- `test_owner_passes_other_denied`：owner 过、他人 `PermissionError`。
- `test_admin_bypasses_owner_check`：Admin 可删/改任何文件。
- `test_can_create_datasource`：Admin 与带 `can_write on Dataset` 权限者 True，Gamma False。
- `test_unauthenticated_raises`：无 g.user 抛 `PermissionError`。
- `test_host_db_lazy`：未注入且无 superset 时 `resolve_model` 抛 `RuntimeError`；注入 fake 后返回 fake。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_permissions.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

按 Interfaces 实现；`permissions` 取角色/权限时统一走 `current_user()` 的 roles 与 permissions 集合（测试注入的 fake user 用同构属性：`id/username/roles/permissions`）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_permissions.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/host_db.py backend/src/my_org/file_db/permissions.py backend/tests/test_permissions.py
git commit -m "feat: add lazy host integration and Superset-native permissions"
```

---

## Task 12: DatasourceManager（Superset 数据源注册与级联）

**Files:**
- Create: `file-db/backend/src/my_org/file_db/datasource.py`
- Test: `file-db/backend/tests/test_datasource.py`

**Interfaces:**
- Consumes: `metadata.MetadataManager`、`query_engine.view_name`、`host_db.resolve_model`、`models.FileDatasource`。
- Produces `datasource.py`：
  ```python
  class DatasourceManager:
      def __init__(self, metadata, query_engine, host_db=host_db): ...
      def available_connections(self) -> list[dict]   # 宿主 Database 中 dialect='filedb'：[{id, name, ...}]
      def create_datasource(self, *, file_id, sheet_id=None, sheet_index=None, datasource_name,
                            description=None, created_by, database_id) -> int   # -> datasource_id
      def list_for_file(self, file_id: str) -> list[FileDatasource]
      def usage_info(self, file_id: str) -> dict      # {datasources, charts, dashboards}
      def delete_datasources_for_file(self, file_id: str, deleted_by: str, reason: str) -> int
  ```
  要点（spec 5.1/5.10/5.12）：
  - `create_datasource`：`resolve_model('SqlaTable')` 实例 → `table_name = view_name(file_id, sheet_index)`、`database_id` = 用户所选 File Database 连接、`description` 透传 → 宿主 session save → 写 `FileDatasource`（datasource_id = 宿主主键）。
  - Superset 原生 tag：尝试调宿主 tag 接口给数据源打标签，`try/except Exception` 降级不阻断主流程。
  - `usage_info`：统计引用该文件数据源的 Slice 数，以及经 Slice 关联的 Dashboard 数。
  - `delete_datasources_for_file`：逐个删宿主 SqlaTable + `FileDatasource` 行，返回删除数（删除日志由 cleanup 统一写）。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_datasource.py` 关键用例（`host_db.set_injectables` 注入 fake SqlaTable/Database/Session）：
- `test_create_datasource_persists`：SqlaTable 字段（table_name/database_id/description）正确，`FileDatasource` 行写入。
- `test_view_name_mapping`：CSV 文件与 Excel sheet_index 的 table_name 分别正确。
- `test_available_connections`：只列 dialect='filedb' 的连接。
- `test_usage_info`：fake Slice 统计 charts/dashboards。
- `test_delete_datasources_for_file`：删除幂等、返回计数、行清空。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_datasource.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

按 Interfaces 实现。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_datasource.py -v`
Expected: 5 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/datasource.py backend/tests/test_datasource.py
git commit -m "feat: add datasource manager for Superset dataset registration"
```

---

## Task 13: 过期清理（cleanup）

**Files:**
- Create: `file-db/backend/src/my_org/file_db/cleanup.py`
- Test: `file-db/backend/tests/test_cleanup.py`

**Interfaces:**
- Consumes: `storage`、`metadata`、`datasource.DatasourceManager`、`query_engine.invalidate`、`config`（`DELETE_REASON_*`、`CLEANUP_THROTTLE_SECONDS`、`EXPIRY_WARNING_DAYS`）。
- Produces `cleanup.py`：
  ```python
  class CleanupManager:
      def __init__(self, storage, metadata, datasource, query_engine): ...
      def delete_file_cascade(self, file_id: str, reason: str, deleted_by: str) -> bool
      def expire_due_files(self, now: datetime | None = None) -> list[str]
      def manual_delete_file(self, file_id: str, deleted_by: str) -> bool
      def upcoming_expiries(self, user_id: str | None = None, days: int = EXPIRY_WARNING_DAYS) -> list[UploadedFile]
      def run_auto_cleanup(self, force: bool = False) -> list[str]
  ```
  级联顺序（spec 5.12，`delete_file_cascade` 为唯一级联入口）：
  1. `datasource.delete_datasources_for_file`（关联数据源）
  2. `query_engine.invalidate(file_id)`（DuckDB 视图）
  3. 删 parquet 缓存目录 `<parquet_dir>/<file_id>/`
  4. `storage.delete_file(storage_path)`（存储文件）
  5. `metadata.delete_file_record(file_id)`（元数据行，cascade 列/表）
  6. `metadata.log_delete(file_id, filename, reason, deleted_by)`（**日志永久保留**，无清理方法）
  - `expire_due_files`：`status=active AND expiry_time < now` → reason=`DELETE_REASON_EXPIRED`；已置 `expired` 状态再删。
  - `run_auto_cleanup`：模块级 `_last_run` 时间戳按 `CLEANUP_THROTTLE_SECONDS`（3600s）节流，`force=True` 跳过节流；spec 5.13 以自动为主、Admin 手动为辅。
  - `upcoming_expiries`：`expiry_time` 在 `now ~ now+days` 窗口内的 active 文件（界面内过期提醒）。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_cleanup.py` 关键用例：
- `test_delete_file_cascade_full`：预置数据源/视图/parquet/存储文件 → 级联后全部清除 + `file_delete_logs` 一条（reason/deleted_by 正确）。
- `test_expire_due_files`：过期文件删、未过期不动、返回删除 id 列表、日志 reason=`expired`。
- `test_manual_delete_reason`：手动删除 reason=`admin_deleted`。
- `test_auto_cleanup_throttled`：连续两次 `run_auto_cleanup()` 第二次为空；`force=True` 立即再跑生效。
- `test_upcoming_expiries`：7 天窗口命中/排除正确。
- `test_missing_file_idempotent`：删除不存在文件返回 False 不抛错。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_cleanup.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

按 Interfaces 实现；级联每步容错（单步失败记日志继续，最后统一回报），但测试断言正常路径全部清空。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_cleanup.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/cleanup.py backend/tests/test_cleanup.py
git commit -m "feat: add expiry cleanup with cascade delete and audit log"
```

---

## Task 14: 服务层——上传与文件（upload_service / file_service）

**Files:**
- Create: `file-db/backend/src/my_org/file_db/services/__init__.py`
- Create: `file-db/backend/src/my_org/file_db/services/upload_service.py`
- Create: `file-db/backend/src/my_org/file_db/services/file_service.py`
- Test: `file-db/backend/tests/test_services_upload_file.py`

**Interfaces:**
- Consumes：Task 3–13 全部组件 + `permissions`。
- Produces `services/__init__.py`：
  ```python
  @dataclass
  class Services:
      upload: "UploadService"; files: "FileService"
      columns: "ColumnService"; datasources: "DatasourceService"   # Task 15
  def build_services(...) -> Services    # 组装真实依赖（db.init_db + storage + parsers + engine + managers）
  ```
- Produces `services/upload_service.py`：
  ```python
  class UploadService:
      def init(self, user_id: str, payload: dict) -> dict      # {upload_id, chunk_size, total_chunks}
      def chunk(self, user_id: str, upload_id: str, index: int, data: bytes) -> dict
      def complete(self, user_id: str, upload_id: str) -> dict  # {file_id}
      def abort(self, user_id: str, upload_id: str) -> dict
      def status(self, user_id: str, upload_id: str) -> dict
  ```
- Produces `services/file_service.py`：
  ```python
  class FileService:
      def list(self, user_id: str) -> list[dict]
      def get(self, user_id: str, file_id: str) -> dict
      def preview(self, user_id: str, file_id: str, sheet_index: int | None = None) -> dict
      def save_config(self, user_id: str, file_id: str, config: dict) -> dict
      def usage(self, user_id: str, file_id: str) -> dict
      def delete(self, user_id: str, file_id: str) -> dict
      def notifications(self, user_id: str) -> list[dict]
  ```
  编排规则：
  - `complete` 后**立即抽样解析 schema**并落列/表元数据（满足 spec 5.10"上传后立即创建数据源"）；Excel→Parquet 保持惰性（spec 5.3）。
  - `save_config` 支持：`datasource_name/description`、Excel 选中 `sheets`（多选，spec 5.8）、CSV `delimiter/encoding`；解析参数变更→重新推断列，但 **`is_user_defined=True` 的列保留用户类型**。
  - 破坏性/属主操作（`save_config`/`delete`）先 `permissions.check_file_owner`。
  - `delete` → `cleanup.delete_file_cascade(reason=DELETE_REASON_USER)`；`notifications` → `cleanup.upcoming_expiries`。
  - `preview` 走 `query_engine.preview`（100 行固定上限）。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_services_upload_file.py` 关键用例（真组件 + tmp 存储 + sqlite 元数据，fake user 注入）：
- `test_upload_full_flow`：init→3 块→complete 返回 file_id，元数据/列已登记（schema 立即解析）。
- `test_chunk_and_status`：进度 dict 字段齐全。
- `test_preview_shape`：columns/rows/totalRows 与列类型。
- `test_save_config_reparses_csv`：改 delimiter/encoding 重推断列且保留用户列类型。
- `test_save_config_excel_sheets`：多选 sheet 落 `is_selected` 标记。
- `test_owner_guard`：非 owner `save_config`/`delete` 抛 `PermissionError`。
- `test_delete_calls_cascade`：级联调用与日志断言。
- `test_notifications_window`：7 天内过期文件出现在列表。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_services_upload_file.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

按 Interfaces 实现；服务层只做编排与 DTO 组装，不写业务规则（规则在 manager/parser 内）。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_services_upload_file.py -v`
Expected: 8 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/services backend/tests/test_services_upload_file.py
git commit -m "feat: add upload and file services with config re-parse"
```

---

## Task 15: 服务层——列与数据源（column_service / datasource_service）

**Files:**
- Create: `file-db/backend/src/my_org/file_db/services/column_service.py`
- Create: `file-db/backend/src/my_org/file_db/services/datasource_service.py`
- Test: `file-db/backend/tests/test_services_columns.py`
- Test: `file-db/backend/tests/test_services_datasource.py`

**Interfaces:**
- Produces `services/column_service.py`：
  ```python
  class ColumnService:
      def list(self, user_id, file_id, sheet_id=None) -> list[dict]
      def update(self, user_id, file_id, column_id, column_type, column_format=None) -> dict
      def import_config(self, user_id, file_id, config_json: str | dict) -> dict   # {applied: n}
      def history(self, user_id, file_id) -> list[dict]
  ```
  编排：`update` → `metadata.update_column_type`（写历史）→ **`query_engine.invalidate(file_id)`**（下次查询重建视图）；`import_config`：`json.loads` 失败抛 `ValueError` → `metadata.import_column_config`（整体校验、原子应用）→ invalidate。
- Produces `services/datasource_service.py`：
  ```python
  class DatasourceService:
      def connections(self, user_id) -> list[dict]
      def create(self, user_id, file_id, sheet_indices: list[int], name, description=None, database_id=None) -> list[dict]
      def list_for_file(self, user_id, file_id) -> list[dict]
      def cleanup(self, user_id, force: bool = False) -> dict
  ```
  编排（spec 5.1/5.13）：
  - `create`：`permissions.can_create_datasource` 否则 `PermissionError`；`database_id` 缺省取 `available_connections()[0]`（多连接时前端必须显式传）；多 sheet 批量创建（每 sheet 一个数据源）；名称冲突自动 `_2/_3` 后缀；逐个 `datasource.create_datasource` 并落 `FileDatasource`。
  - `cleanup`：Admin 才可 `force=True` 手动清理；普通触发走 `run_auto_cleanup` 节流。

- [ ] **Step 1: 写失败测试**

`test_services_columns.py`：update 后 invalidate 被调 + 历史返回；JSON 导入非法整体拒绝（无部分写入）；合法批量返回 applied 计数。
`test_services_datasource.py`：create 权限拒绝（403 语义抛 `PermissionError`）；多 sheet 批量多数据源；名称冲突后缀；connections 过滤 dialect；cleanup 权限与节流透传。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_services_columns.py tests/test_services_datasource.py -v`
Expected: FAIL，`ModuleNotFoundError`

- [ ] **Step 3: 写实现**

按 Interfaces 实现；名称后缀算法：已占用名集合内查 `name`、`name_2`、`name_3`… 取第一个空位。

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_services_columns.py tests/test_services_datasource.py -v`
Expected: 全部 passed

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/services backend/tests/test_services_columns.py backend/tests/test_services_datasource.py
git commit -m "feat: add column and datasource services"
```

---

## Task 16: REST API 层

**Files:**
- Modify: `file-db/backend/src/my_org/file_db/entrypoint.py`（恢复 API import 行）
- Modify: `file-db/backend/src/my_org/file_db/api/__init__.py`（写入 `get_services()` 与 `error_response()`）
- Create: `file-db/backend/src/my_org/file_db/api/files_api.py`
- Create: `file-db/backend/src/my_org/file_db/api/columns_api.py`
- Create: `file-db/backend/src/my_org/file_db/api/datasources_api.py`
- Test: `file-db/backend/tests/test_api.py`

**Interfaces:**
- Consumes: `services.Services`（经模块级 `get_services()`，默认 `build_services()`，测试 monkeypatch 替换）。
- 模式对照 hello-world：`@api(id=..., name=..., description=...)` + `RestApi` + `@expose` `@protect()` `@safe` + openapi docstring；基路径 `/api/v1/extensions/my-org/file-db` 由装饰器按 publisher/name 自动挂载。
- Produces 三个 `RestApi` 子类：
  - `FilesApi`（id=`file_db_files_api`，tag "File DB Files"）：
    `POST /upload/init`、`PUT /upload/<upload_id>/chunks/<int:chunk_index>`（raw bytes body）、`POST /upload/<upload_id>/complete`、`POST /upload/<upload_id>/abort`、`GET /upload/<upload_id>`、`GET /files`、`GET /files/<file_id>`、`GET /files/<file_id>/preview`、`PUT /files/<file_id>/config`、`GET /files/<file_id>/usage`、`DELETE /files/<file_id>`、`GET /notifications`
  - `ColumnsApi`（id=`file_db_columns_api`）：
    `GET /files/<file_id>/columns`、`PUT /files/<file_id>/columns/<column_id>`、`POST /files/<file_id>/columns/import`、`GET /files/<file_id>/columns/history`
  - `DatasourcesApi`（id=`file_db_datasources_api`）：
    `GET /datasources/connections`、`POST /datasources`、`GET /files/<file_id>/datasources`、`POST /admin/cleanup`
- 约定：
  - 全端点 `@protect() @safe`；JSON body（chunk 除外，`application/octet-stream`）。
  - 响应 `self.response(200, result=...)`；异常映射集中在 `api/__init__.py: error_response(exc)`：`PermissionError→403`、`ValueError→400`、`KeyError/FileNotFoundError→404`、兜底 500。
  - 每端点写 hello-world 同款 openapi docstring（description + 200 schema + 401 `$ref`）。
  - 所有方法只做：解析请求 → 调 service → 封装响应；不写业务逻辑。

- [ ] **Step 1: 写失败测试**

`file-db/backend/tests/test_api.py` 关键用例（monkeypatch `get_services` 返回 fake services；monkeypatch Api 类的 `response`/`response_4xx` 为轻量 stub；`app.test_request_context()` 中直接调端点方法）：
- 逐端点断言：路径参数/body 正确传给对应 service 方法、返回 `result` 结构正确。
- 异常映射：`PermissionError`→403、`ValueError`→400、未知 id→404。
- chunk 端点：binary body 透传 `service.chunk`。
- `@api` 注册冒烟：三个类进入 `superset_core` 注册表。

- [ ] **Step 2: 运行测试确认失败**

Run: `python -m pytest tests/test_api.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'my_org.file_db.api.files_api'`

- [ ] **Step 3: 写实现**

按 Interfaces 实现；`entrypoint.py` 恢复：
```python
from .api import columns_api, datasources_api, files_api  # noqa: E402,F401
```
（保留 Task 1 的 `register_extension()` 先行顺序。）

- [ ] **Step 4: 运行测试确认通过**

Run: `python -m pytest tests/test_api.py -v` 以及全量 `python -m pytest tests -v`
Expected: 全部 passed（后端整体绿）

- [ ] **Step 5: 提交**

```bash
git add backend/src/my_org/file_db/api backend/src/my_org/file_db/entrypoint.py backend/tests/test_api.py
git commit -m "feat: add REST API layer for files, columns and datasources"
```

---

## Task 17: 前端脚手架与 API 客户端

**Files:**
- Create: `file-db/frontend/package.json`
- Create: `file-db/frontend/tsconfig.json`
- Create: `file-db/frontend/webpack.config.js`
- Create: `file-db/frontend/vitest.config.ts`
- Create: `file-db/frontend/src/types.ts`
- Create: `file-db/frontend/src/api/client.ts`
- Test: `file-db/frontend/src/api/client.test.ts`

**Interfaces:**
- `package.json`：name `@my-org/file-db`，private；scripts：`test: "vitest run"`、`start: "webpack serve --mode development"`、`build: "webpack --stats-error-details --mode production"`；dependencies `react-dropzone`；peerDependencies `@apache-superset/core: "*"`、`react: ^17.0.2`、`react-dom: ^17.0.2`、`antd`；devDependencies 对照 hello-world（ts-loader/typescript/webpack*/@types/react/@babel/*）+ `vitest`、`jsdom`、`@testing-library/react`、`@testing-library/jest-dom`。
- `webpack.config.js`：对照 hello-world 逐项照抄，仅改三处：ModuleFederationPlugin `name: "myOrg_fileDb"`、`exposes: { "./index": "./src/index.tsx" }`、`publicPath` 读 `../extension.json` 得 `/api/v1/extensions/my-org/file-db/`；`externals: { "@apache-superset/core": "superset" }` 与 react/react-dom/antd singleton 共享保持一致。
- `vitest.config.ts`：`environment: "jsdom"`、`globals: true`、include `src/**/*.test.{ts,tsx}`、`setupFiles` 指向 `src/setupTests.ts`（仅 `import "@testing-library/jest-dom"`）。
- `src/types.ts`（字段与后端服务 JSON 一一对应）：`UploadedFileDto`、`SheetDto`、`ColumnDto`、`PreviewDto`、`FileConfigDto`、`UploadInitDto`、`UploadStatusDto`、`DatasourceDto`、`ConnectionDto`、`ChangeLogDto`、`NotificationDto`、`ApiError`。
- `src/api/client.ts`：
  ```ts
  export const API_BASE = "/api/v1/extensions/my-org/file-db";
  export class ApiClient {
    get(path: string): Promise<any>;
    post(path: string, body?: unknown): Promise<any>;
    put(path: string, body?: unknown): Promise<any>;
    del(path: string): Promise<any>;
    putBinary(path: string, data: Blob): Promise<any>;
  }
  ```
  行为：`fetch` + `credentials: "same-origin"`；`X-CSRFToken` 头取 `document.cookie` 的 `csrftoken`；JSON 编解码；非 2xx 抛 `ApiError {status, message}`（message 取响应 `message`/`error` 字段兜底状态文本）；`putBinary` 用 `Content-Type: application/octet-stream`。

- [ ] **Step 1: 脚手架（非 TDD）**

`cd file-db/frontend && npm install`（生成 lock 后提交）。tsconfig：`jsx: react-jsx`?——**锁定 `jsx: "react"`（React 17 classic）**、`target: ES2019`、`module: ESNext`、`strict: true`、`moduleResolution: node`。

- [ ] **Step 2: 写失败测试**

`src/api/client.test.ts` 关键用例（mock global.fetch）：
- URL 拼装（`API_BASE + path`）与 method/body 正确。
- CSRF 头注入（伪造 `document.cookie="csrftoken=abc"`）。
- 2xx JSON 解析返回 data；204 返回 null。
- 非 2xx 抛 `ApiError`（status/message）。
- `putBinary` 透传 Blob 与 octet-stream 头。

- [ ] **Step 3: 运行测试确认失败**

Run: `npm test`（cwd = `file-db/frontend`）
Expected: FAIL，`Cannot find module './client'`

- [ ] **Step 4: 写实现并确认通过**

实现 `client.ts`；Run: `npm test` → 5 passed；`npm run build` 可产出 dist（冒烟）。

- [ ] **Step 5: 提交**

```bash
git add frontend
git commit -m "feat: scaffold frontend with module federation and api client"
```

---

## Task 18: 前端 UploadManager（队列 / 3 并发 / 断点续传）

**Files:**
- Create: `file-db/frontend/src/upload/UploadManager.ts`
- Test: `file-db/frontend/src/upload/UploadManager.test.ts`

**Interfaces:**
- Consumes: `ApiClient`（Task 17）、`types.ts`。
- Produces：
  ```ts
  export type UploadEvents = {
    onProgress?: (clientFileId: string, percent: number) => void;
    onFileDone?: (clientFileId: string, serverFileId: string) => void;
    onFileError?: (clientFileId: string, message: string) => void;
    onQueueChange?: (activeCount: number) => void;
  };
  export class UploadManager {
    constructor(api: ApiClient, events?: UploadEvents, opts?: { concurrency?: number });
    enqueue(file: File): string;      // 返回 clientFileId（内部生成）
    cancel(clientFileId: string): void;
    get activeCount(): number;
  }
  ```
  行为（spec 5.5）：
  - 队列并发上限 3（`opts.concurrency` 默认 3）；`onQueueChange` 在活跃数变化时触发。
  - 单文件流程：`POST /upload/init`（filename/total_size/file_type 由 File 的 name/size/扩展名推导）→ 以 init 返回的 `chunk_size`（8MB）顺序 `PUT /upload/<id>/chunks/<i>` → `POST /upload/<id>/complete`。
  - 进度 = 已确认字节 / total_size × 100（向下取整），每块确认后触发 `onProgress`。
  - 单块失败重试 3 次（500ms 指数退避）；重试**只补缺块**（服务端幂等 = 断点续传）；3 次后文件终态失败 `onFileError`。
  - `cancel`：终止该文件剩余块、调 `POST /upload/<id>/abort`、队列剔除。

- [ ] **Step 1: 写失败测试**

`src/upload/UploadManager.test.ts`（mock ApiClient/fetch）：
- 并发上限：同 enqueue 5 个文件，同时在飞 init ≤ 3。
- 块序列：总大小 `chunk*2.5` → 3 块、末块小、顺序 PUT。
- 重试续传：第 2 块首次 500 → 重试成功，仅补该块。
- 进度回调：0/33/66/100 序列合理。
- cancel：剩余块不再发、abort 被调、onQueueChange 更新。
- 终态失败：3 次重试全败 → onFileError。

- [ ] **Step 2: 运行测试确认失败**

Run: `npm test`
Expected: FAIL，`Cannot find module './UploadManager'`

- [ ] **Step 3: 写实现并确认通过**

实现（Promise 队列 + 每文件状态机 `queued/uploading/done/error/cancelled`）；Run: `npm test` → 6 passed。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/upload
git commit -m "feat: add frontend upload manager with concurrency and resume"
```

---

## Task 19: 上传与预览组件（FileUpload / DataPreview）

**Files:**
- Create: `file-db/frontend/src/components/FileUpload.tsx`
- Create: `file-db/frontend/src/components/DataPreview.tsx`
- Test: `file-db/frontend/src/components/FileUpload.test.tsx`
- Test: `file-db/frontend/src/components/DataPreview.test.tsx`

**Interfaces:**
- Consumes：`react-dropzone`、`UploadManager`、`types.ts`。
- Produces（Props 锁定）：
  ```ts
  FileUpload:  { manager: UploadManager; onUploaded: (fileId: string) => void; onError: (msg: string) => void }
  DataPreview: { fileId: string; data: PreviewDto; columnTypes?: Record<string, { type: string; format?: string }>;
                 sheetIndex?: number; onSheetChange?: (i: number) => void }
  ```
- `FileUpload`：react-dropzone（accept `.csv/.xls/.xlsx`，multiple）；文案"拖放CSV或Excel文件到这里，或点击选择文件"，拖拽中变色提示"拖放文件到这里..."；逐文件前置校验（csv ≤ 150MB、excel ≤ 500MB、文件名 ≤ 255 且无特殊字符），违规即时 `onError` 且不入队；合法文件 `manager.enqueue`，逐文件进度条；每文件 `onFileDone` → `onUploaded(serverFileId)`，`onFileError` → `onError`。
- `DataPreview`：标题"数据预览" + "显示前 N 行，共 {totalRows} 行"；表头列名 + 类型徽标（`columnTypes` 覆盖显示）；Excel 时顶部 sheet tab（当前 `sheetIndex`，点击 `onSheetChange`）；空值渲染 `-`；loading/error 两态。

- [ ] **Step 1: 写失败测试**

`FileUpload.test.tsx`：dropzone 文案与拖拽态切换、超限 csv 被拒且 onError、合法文件入队（mock manager.enqueue）、进度条渲染。
`DataPreview.test.tsx`：表头列名/类型徽标、行渲染与空值 `-`、totalRows 文案、sheet tab 高亮与点击回调。

- [ ] **Step 2: 运行测试确认失败**

Run: `npm test`
Expected: FAIL，`Cannot find module './FileUpload'`

- [ ] **Step 3: 写实现并确认通过**

组件用函数式 + hooks；样式用内联 class（不引 CSS 框架）；Run: `npm test` → 全部 passed。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components
git commit -m "feat: add file upload and data preview components"
```

---

## Task 20: 配置与列类型组件（FileConfig / ColumnTypeEditor）

**Files:**
- Create: `file-db/frontend/src/components/FileConfig.tsx`
- Create: `file-db/frontend/src/components/ColumnTypeEditor.tsx`
- Test: `file-db/frontend/src/components/FileConfig.test.tsx`
- Test: `file-db/frontend/src/components/ColumnTypeEditor.test.tsx`

**Interfaces:**
- Produces（Props 锁定）：
  ```ts
  FileConfig: { fileId: string; fileType: "csv" | "excel"; sheets?: SheetDto[]; columns?: ColumnDto[];
                initial?: FileConfigDto; onSave: (cfg: FileConfigDto) => void }
  ColumnTypeEditor: { columns: ColumnDto[]; onUpdate: (columnId: string, type: string, format?: string) => void;
                      onImport: (json: string) => void; history?: ChangeLogDto[] }
  ```
- `FileConfig`：数据源名称（必填）+ 描述输入；Excel → 工作表**多选** checkbox 列表（含名称/行列数，spec 5.8）；CSV → 分隔符下拉（`,` `;` `\t` `|` 空格）+ 编码下拉（utf-8/gbk/gb2312/latin-1）；"保存配置"按钮（名称为空禁用并提示）；`initial` 回填。
- `ColumnTypeEditor`：列类型表格（列名 / 类型下拉五选一 / 格式输入 / 示例值前 3 个）；格式输入**仅 datetime 显示**（placeholder `%Y-%m-%d`，strptime 格式）；"保存列类型"仅对变更行调 `onUpdate`；JSON 导入区（textarea + 导入按钮 → `onImport`，失败信息红色展示）；修改历史折叠面板（history 列表）。

- [ ] **Step 1: 写失败测试**

`FileConfig.test.tsx`：名称必填校验/禁用态、工作表多选勾选状态、分隔符与编码选项齐全、`initial` 回填、保存回调 payload。
`ColumnTypeEditor.test.tsx`：类型下拉变更、datetime 才显示格式输入、仅变更行触发 onUpdate、示例值渲染、导入按钮与错误展示、history 折叠内容。

- [ ] **Step 2: 运行测试确认失败**

Run: `npm test`
Expected: FAIL，`Cannot find module './FileConfig'`

- [ ] **Step 3: 写实现并确认通过**

Run: `npm test` → 全部 passed。

- [ ] **Step 4: 提交**

```bash
git add frontend/src/components
git commit -m "feat: add file config and column type editor components"
```

---

## Task 21: 文件管理、通知与入口注册（FileList / Notifications / index.tsx）

**Files:**
- Create: `file-db/frontend/src/components/FileList.tsx`
- Create: `file-db/frontend/src/components/Notifications.tsx`
- Create: `file-db/frontend/src/index.tsx`
- Test: `file-db/frontend/src/components/FileList.test.tsx`
- Test: `file-db/frontend/src/components/Notifications.test.tsx`

**Interfaces:**
- Produces（Props 锁定）：
  ```ts
  FileList: { files: UploadedFileDto[]; onDelete: (fileId: string) => void; onRefresh: () => void }
  Notifications: { items: NotificationDto[]; onDismiss: (id: string) => void }
  ```
- `FileList`：表格列 文件名/大小/类型/行数/列数/上传时间/过期时间（倒计时文案）/使用情况（数据源·图表数）/操作；删除按钮 → **二次确认弹窗**（文案含"将同时删除关联的数据源"，spec 5.12）→ 确认后 `onDelete`。
- `Notifications`：过期提醒横幅（"N 个文件将在 7 天内过期"，逐条列出文件名与到期日），逐条 `onDismiss` 关闭。
- `index.tsx`：`views.registerView({ id: "my-org.file-db.panel", name: "文件数据库" }, "sqllab.panels", () => <FileDbPanel />)`；`FileDbPanel`（index.tsx 内联容器）：tab 流程"上传 → 配置 → 管理"，持有 `ApiClient`/`UploadManager` 实例与当前 `fileId`/预览数据/列配置；接线：上传完成 → 拉 `GET /files/<id>` + `GET /files/<id>/columns` + preview 进入配置页；保存配置/列类型/建数据源/删除文件对应 service 端点；通知栏读 `GET /notifications`。

- [ ] **Step 1: 写失败测试**

`FileList.test.tsx`：列渲染、删除点击弹二次确认、确认才触发 onDelete、倒计时文案。
`Notifications.test.tsx`：横幅内容、逐条关闭回调、空列表不渲染。
（index.tsx 接线由 Task 22 E2E 兜底，此处用一个 `FileDbPanel` 冒烟测试验证 tab 切换与回调 mock 接线。）

- [ ] **Step 2: 运行测试确认失败**

Run: `npm test`
Expected: FAIL，`Cannot find module './FileList'`

- [ ] **Step 3: 写实现并确认通过**

Run: `npm test` → 全部 passed；`npm run build` 通过。

- [ ] **Step 4: 提交**

```bash
git add frontend/src
git commit -m "feat: add file list, notifications and extension entry panel"
```

---

## Task 22: 集成、打包与部署

**Files:**
- Create: `file-db/Dockerfile`
- Create: `file-db/docker-compose.yml`
- Create: `file-db/superset_config.py`
- Create: `file-db/init-superset.sh`
- Create: `file-db/DEPLOY.md`
- Modify: `file-db/backend/pyproject.toml`（如打包缺前端产物，`include` 增 `"frontend/dist/**"`）

**要点：**
- **Dockerfile**（对照 hello-world）：`FROM apache/superset:6.1.0` → `USER root` → `COPY backend/requirement.txt` + `/app/.venv/bin/python -m pip install -r`（含 psycopg2-binary/duckdb/pandas/openpyxl/chardet/xlrd）→ `COPY file-db-0.1.0.supx /app/extensions/` → `COPY superset_config.py /app/pythonpath/` + `ENV SUPERSET_CONFIG_PATH=...` → `COPY init-superset.sh`（chmod +x）→ `USER superset` → `CMD ["/app/init-superset.sh"]`。
- **superset_config.py**（对照 hello-world）：`FEATURE_FLAGS = {"ENABLE_EXTENSIONS": True}`、`EXTENSIONS_PATH = "/app/extensions"`、`SECRET_KEY`、`SQLALCHEMY_DATABASE_URI = "postgresql://superset_meta:superset_meta_pass@pg-db:5432/superset_metadata"`、`SQLALCHEMY_EXAMPLES_URI` 同源、连接池调优；环境变量 `FILE_DB_UPLOAD_ROOT` 透传给扩展配置。
- **docker-compose.yml**：`pg-db`（`postgres:15`，`POSTGRES_DB=superset_metadata`、`POSTGRES_USER=superset_meta`、`POSTGRES_PASSWORD=superset_meta_pass`，volume `pgdata:/var/lib/postgresql/data`）+ `superset`（`build: .`，`ports: "8088:8088"`，`environment: FILE_DB_UPLOAD_ROOT=/data/uploads`，volume `./data/uploads:/data/uploads`，`depends_on: pg-db`）。
- **init-superset.sh**（对照 hello-world）：`superset db current` 探测首次启动 → `db upgrade` → `fab create-admin`（|| true）→ `superset init` → `exec /usr/bin/run-server.sh`。
- **打包**（cwd = `file-db`）：`cd frontend && npm ci && npm run build` → `superset-extensions validate && superset-extensions bundle` 产出 `file-db-0.1.0.supx`；`unzip -l file-db-0.1.0.supx` 验证含 `frontend/dist`（remoteEntry.*.js 等），缺则在 pyproject `include` 加 `"frontend/dist/**"` 重打包。
- **DEPLOY.md** 内容：系统要求（Docker/Compose、磁盘按上传量）；构建顺序（前端 → bundle → 镜像）；环境变量表（`FILE_DB_UPLOAD_ROOT`、`FILE_DB_METADATA_URI`）；**Admin 前置操作**：登录后在"数据库"创建一条 SQLAlchemy URI 为 `filedb://` 的连接（命名如 "File Database"），配置上传大目录挂载；升级与备份说明（PG 挂卷 + 上传目录挂卷）。

- [ ] **Step 1: 写集成产物**

按上述要点写五个文件；`requirement.txt` 确认包含全部运行时依赖。

- [ ] **Step 2: 构建与校验**

```bash
# 后端测试（cwd = file-db/backend）
python -m pytest tests -v
# 前端（cwd = file-db/frontend）
npm test && npm run build
# 打包（cwd = file-db）
superset-extensions validate && superset-extensions bundle
unzip -l file-db-0.1.0.supx | grep -E "frontend/dist|\.py$"
```
Expected: 测试全绿；validate 通过；supx 同时含后端 py 与前端 dist。

- [ ] **Step 3: E2E 验收清单（人工逐项走查）**

```bash
docker compose up --build   # cwd = file-db，访问 http://localhost:8088，admin/admin
```
1. SQL Lab 出现"文件数据库"面板；拖拽上传 GBK+分号 CSV（≤150MB）显示逐文件进度；
2. 预览 100 行、显示推断列类型；
3. 列类型改为 datetime（format `%Y-%m-%d`）保存生效（SQL Lab 可按日期过滤）；
4. 上传多工作表 xlsx，多选工作表批量创建数据源（名称冲突自动 `_2` 后缀）；
5. SQL Lab 能查询各 dataset，**跨文件 JOIN** 可用；
6. 基于数据源创建 chart + dashboard；
7. 删除文件：二次确认 → 关联数据源消失、存储/parquet/视图清除，`file_delete_logs` 有记录且 `column_type_change_logs` 保留；
8. `POST /api/v1/extensions/my-org/file-db/admin/cleanup`（Admin）清理过期文件；界面通知横幅显示 7 天内过期文件。

- [ ] **Step 4: 修复回归并提交**

E2E 发现的问题修复后重跑对应单测；最后提交：

```bash
git add Dockerfile docker-compose.yml superset_config.py init-superset.sh DEPLOY.md backend/pyproject.toml
git commit -m "chore: add docker integration, packaging and deployment docs"
```

---

## Definition of Done（全量验证）

```bash
# 后端（cwd = file-db/backend）
python -m pytest tests -v
# 前端（cwd = file-db/frontend）
npm test
# 打包（cwd = file-db）
superset-extensions validate && superset-extensions bundle
# E2E（cwd = file-db）
docker compose up --build
```

- [ ] 后端全部测试通过（含权限、级联删除、历史永久保留断言）
- [ ] 前端全部测试通过
- [ ] `file-db-0.1.0.supx` 生成且包含前端产物
- [ ] E2E 验收清单 8 项全部通过
- [ ] 无任何 Superset 源代码修改（全部变更仅在 `file-db/` 新目录内）
- [ ] 22 个任务全部提交，commit message 前缀规范


任务结构：

阶段	任务	内容
后端基础	Task 1–2（已有）	脚手架/常量、ORM 模型
存储与解析	Task 3–5	2026-09-25-file-database-engine.md:788（含目录穿越防护）、schema 推断 + CSV 解析、Excel 解析（含 xlrd）
元数据	Task 6–7	MetadataManager、列类型管理与永久修改历史
查询链路	Task 8–10	分块断点续传、DuckDB 视图引擎、SQLAlchemy filedb 方言 + DBAPI shim
宿主集成	Task 11–13	惰性 host_db + 权限、数据源注册、过期清理级联
服务与 API	Task 14–16	服务层编排、REST API（Task 16 与 Task 1 中 entrypoint 注释的编号约定一致）
前端	Task 17–21	API 客户端、UploadManager（3 并发/续传）、上传/预览/配置/列类型/管理组件
交付	Task 22 + DoD	Docker/Compose/DEPLOY.md、8 项 E2E 验收清单、全量验证命令