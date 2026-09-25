# file-db 扩展部署文档

Superset 文件数据库引擎扩展（`my-org/file-db`）：拖拽上传 CSV/Excel → 配置 schema → 注册为 Superset 数据源（DuckDB 查询引擎 + `filedb` SQLAlchemy 方言）。不修改 Superset 源代码，通过 `.supx` 扩展机制交付。

## 1. 系统要求

- Docker 20+ 与 Docker Compose v2
- 磁盘空间：镜像约 2GB + PostgreSQL 卷 + 上传文件目录（按上传量规划，CSV ≤ 150MB / Excel ≤ 500MB / 文件保留 180 天）
- 内存建议 ≥ 4GB（DuckDB 查询与 Excel 解析会占用内存）

## 2. 构建顺序

```bash
# 1) 构建前端（产出 frontend/dist）
cd frontend && npm ci && npm run build && cd ..

# 2) 校验并打包扩展（产出 file-db-0.1.0.supx）
superset-extensions validate
superset-extensions bundle

# 3) 验证包内容（应同时包含后端 py 与前端 dist）
unzip -l file-db-0.1.0.supx | grep -E "frontend/dist|\.py$"

# 4) 构建镜像并启动（首次启动自动执行迁移并创建 admin/admin）
docker compose up --build -d
```

访问 `http://localhost:8088`，账号 `admin` / `admin`。

测试：

```bash
# 后端（cwd = backend）
python -m pytest tests -v
# 前端（cwd = frontend）
npm test
```

## 3. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `FILE_DB_UPLOAD_ROOT` | `/data/uploads` | 上传文件大目录（Admin 配置，系统自动创建用户子目录）；compose 中已挂载 `./data/uploads:/data/uploads` |
| `FILE_DB_METADATA_URI` | （无） | 可选：覆盖扩展元数据库连接；缺省复用宿主 `SQLALCHEMY_DATABASE_URI` |
| `SUPERSET_CONFIG_PATH` | `/app/pythonpath/superset_config.py` | 宿主配置路径（镜像内已设置） |

## 4. Admin 前置操作（部署后必做）

1. 登录 Superset（admin/admin）。
2. 进入 **设置 → 数据库 → ＋ 数据库**，在 **Supported databases** 下拉中选择 **File Database**，创建连接：
   - 显示名称：`File Database`
   - SQLAlchemy URI：`filedb://`
3. （可选）创建多条 `filedb://` 连接，供不同用户/团队选择（数据源创建时可指定）。
4. 上传目录挂载：确认 `./data/uploads` 持久化（compose 已配置），生产环境替换为大容量卷。

## 5. 升级与备份

- **备份**：PostgreSQL 数据卷（`pgdata`）+ 上传目录（`./data/uploads`）。两者包含全部元数据（含永久保留的删除日志与列类型修改历史）与原始文件。
- **升级**：重新执行构建顺序（前端 → bundle → `docker compose up --build -d`）；`init-superset.sh` 检测到已有版本记录时跳过初始化，仅启动服务。
- **回滚**：保留旧镜像与旧 `.supx`，回切镜像版本即可；扩展表结构无破坏性变更。

## 6. E2E 验收清单

1. SQL Lab 出现"文件数据库"面板；拖拽上传 GBK+分号 CSV（≤150MB）显示逐文件进度；
2. 预览 100 行、显示推断列类型；
3. 列类型改为 datetime（format `%Y-%m-%d`）保存生效（SQL Lab 可按日期过滤）；
4. 上传多工作表 xlsx，多选工作表批量创建数据源（名称冲突自动 `_2` 后缀）；
5. SQL Lab 能查询各 dataset，**跨文件 JOIN** 可用；
6. 基于数据源创建 chart + dashboard；
7. 删除文件：二次确认 → 关联数据源消失、存储/parquet/视图清除，`file_delete_logs` 有记录且 `column_type_change_logs` 保留；
8. `POST /extensions/my-org/file-db/admin/cleanup`（Admin）清理过期文件；界面通知横幅显示 7 天内过期文件。
