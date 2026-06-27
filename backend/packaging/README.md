# 小票夹后端 · EXE 打包

把 FastAPI 后端冻结成**绿色 EXE**,让不懂命令行的亲友也能自托管——每人跑自己的实例(隐私优先,不共享服务器),用自己的 Android App 连。

## 构建

```
cd backend
scripts\build_backend_exe.ps1          # 增量
scripts\build_backend_exe.ps1 -Clean   # 连构建 venv 一起重建
```

产物:文件夹 `backend\dist\ticketbox-backend\`(内含 `ticketbox-backend.exe` + `_internal\`;onedir,**窗口化 console=False**,ADR-0047 §8)。整个文件夹一起拷贝/分发,不能只拿出 exe。

构建用**独立的 `.venv-build`**(uv 托管 Python 3.11),不污染运行时 `.venv`。**不含 OCR**(rapidocr/onnxruntime/opencv 太重且可选)——需要 OCR 的话另装 `requirements-ocr.txt` 跑源码版。

## 一键安装(给自托管小白)

已装好 PostgreSQL 后,把 `ticketbox-backend\` 文件夹、`install_ticketbox.ps1`、
`fix_table_owners.sql`(可选,属主修复兜底)放同一目录,右键
`install_ticketbox.ps1` →「用 PowerShell 运行」。向导会:

1. 定位 `psql.exe`(环境变量 `PG_BIN` → `PATH` → `C:\Program Files\PostgreSQL\<最高版本>\bin`);
2. 用超级用户(装库时设的 `postgres` 口令)**只建空角色 + 空库**(`OWNER=ticketbox`);
3. 生成 `ticketbox-data\.env`(**无 BOM**),`DATABASE_URL` 指向应用角色;
4. **首次启动 EXE 以应用角色 `ticketbox` 连库建表**——表属主自然归位(堵 owner 错位陷阱,
   见 [POSTGRES_MIGRATION.md](../../docs/runbook/POSTGRES_MIGRATION.md) §3),并自检非
   `ticketbox` 属主的表为 0,异常时跑 `fix_table_owners.sql` 归位;
5. 经一次性 HTTP bootstrap 创建 owner 身份,凭证 + **Android 配对码**写入
   `ticketbox-data\owner-bootstrap.txt`,随后清掉 `.env` 里的一次性 bootstrap 开关;
6. 注册开机自启任务计划(`-SkipScheduledTask` 可跳过)。

```
powershell -ExecutionPolicy Bypass -File install_ticketbox.ps1
# 可选参数:-Port 8000 -DbPort 5432 -PublicBaseUrl https://api.example.com
#           -SuperPassword <postgres口令>（不传则交互询问;trust 模式传 ""）
#           -DbPassword <已存在 ticketbox 角色的口令>（重跑既有安装时)
```

红线:建角色/建库才用超级用户,**建表只能由应用角色连接**;`.env` 不带 BOM;不依赖
Docker/WSL/PS7。**当前档 A 假设本机已装 PostgreSQL 服务**(免装 PG 的捆绑方案 = 档 B,待 ADR)。

## 运行与数据

双击 `ticketbox-backend\ticketbox-backend.exe`,默认监听 `127.0.0.1:8000`(窗口化,不弹控制台窗口)。

所有**可写数据**放在 EXE 旁的 `ticketbox-data/`(onedir 程序文件夹内、与 `_internal\` 同级;冻结的 bundle 本身只读/临时):

```
ticketbox-backend/
├── ticketbox-backend.exe
├── _internal/          PyInstaller 运行时（依赖 + alembic.ini + migrations/ + 静态资源）
└── ticketbox-data/
    ├── uploads/            小票图片
    ├── logs/               运行日志（backend.log，窗口化无控制台时排查看这里；轮转 ~5MB×3）
    ├── backups/            PostgreSQL 备份归档（pg_dump .dump；Owner Console「备份」按钮 / 计划任务写到这里）
    └── .env                可选：用户覆盖配置（DATABASE_URL / PUBLIC_BASE_URL / OCR_* / 端口 等）
```

`launch.py` 在 import `app.*` 之前把 `UPLOAD_DIR` 指向这个目录、并把 uvicorn + app 日志配到 `logs/backend.log`(windowed `console=False` 无 stdout,改写文件);若存在 `ticketbox-data/.env` 则**优先**采用其中的值(`override=True`)。`DATABASE_URL` 不在这里默认——后端是 PostgreSQL-only,要么在 `.env` 里设、要么回落到 `app.config` 的本机 PostgreSQL 默认(EXE 假设本机已装 PostgreSQL 服务)。

可用环境变量(或写进 `ticketbox-data/.env`):

| 变量 | 默认 | 说明 |
|---|---|---|
| `TICKETBOX_HOST` | `127.0.0.1` | bind host |
| `TICKETBOX_PORT` | `8000` | 端口 |
| `DATABASE_URL` | （`app.config` 本机 PostgreSQL 默认） | 数据库（PostgreSQL-only，见下） |
| `UPLOAD_DIR` | `<data>/uploads` | 上传目录 |
| `PUBLIC_BASE_URL` | （空） | 隧道公网地址（如有） |

### 备份与恢复

备份归档（`pg_dump -Fc` 的 `.dump`）写在 `ticketbox-data/backups/`（Owner Console 的「备份」按钮、计划任务都写这里——和 `app.config.DATA_ROOT` 一致）。数据库本身在本机 PostgreSQL 服务里，**不**在这个目录，恢复要用 `pg_restore`:

1. 停掉 `ticketbox-backend.exe`；
2. 用 `pg_restore` 把 `ticketbox-data/backups/` 里某个 `ticketbox-*.dump` 恢复到目标库（完整步骤见 [POSTGRES_MIGRATION.md](../../docs/runbook/POSTGRES_MIGRATION.md) §2）；
3. 重新双击 EXE。

源码/家庭服务器部署的备份脚本（`backend/scripts/backup_database.ps1`、`scripts/maintenance_ticketbox.ps1`）已改为**跟随数据根**:设了 `TICKETBOX_DATA_DIR` 用它、否则用 `backend/`,所以它们与 app 写备份的位置始终一致。诊断类脚本（`diagnose_ticketbox.ps1` 等）仍按源码 `backend/` 布局,是家庭服务器自用工具,不用于冻结 EXE。

## 冻结要点（给维护者）

- 入口 `packaging/launch.py`;spec `packaging/ticketbox-backend.spec`。
- 形态:**onedir + `console=False`**(ADR-0047 §8)。`EXE(exclude_binaries=True)` + `COLLECT(...)` → `dist/ticketbox-backend/`(EXE + `_internal/`)。窗口化进程无 `sys.stdout/stderr`,所以 `launch.py` 在起 uvicorn 前用 `logging.config.dictConfig` 把 uvicorn + app 日志接到 `DATA_ROOT/logs/backend.log`(`RotatingFileHandler`),并给 uvicorn 传 `log_config=None`——否则 uvicorn 默认配置会写 `ext://sys.stdout`,`None.write` 崩。
- `app/config.py`、`app/database` 用 `Path(__file__).parents[N]` 解析路径,冻结后指向 `sys._MEIPASS`(onedir 下即 `_internal/` 目录)。所以 spec 把 `alembic.ini` 和 `migrations/` 打到 **bundle 根**(`backend_root`),`static/` `templates/` 留在 `app/` 下。
- 首次启动:`init_db()` 先 `Base.metadata.create_all` 建当前 schema,再尝试用打包的 `alembic.ini` + `migrations/` 把 `alembic_version` stamp 到 head(缺这两个文件会优雅跳过,新库仍可用)。
- 动态导入(uvicorn 的 loop/protocol、`app.*` 路由、postgresql 方言 + psycopg 驱动)由 spec 的 `collect_submodules` + `hiddenimports` 兜底;新增依赖若运行时报 `ModuleNotFoundError`,在 spec 的 `hiddenimports` 补一行再重建。
- PyInstaller 冻结 EXE 可能触发杀软误报(无签名)。正式分发建议代码签名。

## 与 GUI 管理器的关系

`desktop/` 的后端管理器（薄进程壳 + 状态面板）当前 spawn `python -m uvicorn`;后续可让它改 spawn 这个 EXE,实现「双击即开 GUI + 后端」的一体化分发。
