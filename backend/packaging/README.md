# 小票夹后端 · EXE 打包

把 FastAPI 后端冻结成**单文件 EXE**,让不懂命令行的亲友也能自托管——每人跑自己的实例(隐私优先,不共享服务器),用自己的 Android App 连。

## 构建

```
cd backend
scripts\build_backend_exe.ps1          # 增量
scripts\build_backend_exe.ps1 -Clean   # 连构建 venv 一起重建
```

产物:`backend\dist\ticketbox-backend.exe`(一文件)。

构建用**独立的 `.venv-build`**(uv 托管 Python 3.11),不污染运行时 `.venv`。**不含 OCR**(rapidocr/onnxruntime/opencv 太重且可选)——需要 OCR 的话另装 `requirements-ocr.txt` 跑源码版。

## 运行与数据

双击 `ticketbox-backend.exe`,默认监听 `127.0.0.1:8000`。

所有**可写数据**放在 EXE 旁的 `ticketbox-data/`(冻结的 bundle 本身只读/临时):

```
ticketbox-backend.exe
ticketbox-data/
├── ticketbox.db        SQLite 账本库（首次启动 create_all 自动建表）
├── uploads/            小票图片
├── backups/            SQLite 备份快照（Owner Console「备份」按钮 / 计划任务写到这里）
└── .env                可选：用户覆盖配置（PUBLIC_BASE_URL / OCR_* / 端口 等）
```

`launch.py` 在 import `app.*` 之前把 `DATABASE_URL` / `UPLOAD_DIR` 指向这个目录;若存在 `ticketbox-data/.env` 则**优先**采用其中的值(`override=True`),其余回落到上面的默认。

可用环境变量(或写进 `ticketbox-data/.env`):

| 变量 | 默认 | 说明 |
|---|---|---|
| `TICKETBOX_HOST` | `127.0.0.1` | bind host |
| `TICKETBOX_PORT` | `8000` | 端口 |
| `DATABASE_URL` | `sqlite:///<data>/ticketbox.db` | 数据库 |
| `UPLOAD_DIR` | `<data>/uploads` | 上传目录 |
| `PUBLIC_BASE_URL` | （空） | 隧道公网地址（如有） |

### 备份与恢复

备份快照写在 `ticketbox-data/backups/`（Owner Console 的「备份」按钮、计划任务都写这里——和 `app.config.DATA_ROOT` 一致）。冻结 EXE **自包含**,恢复不依赖源码版脚本:

1. 停掉 `ticketbox-backend.exe`；
2. 把 `ticketbox-data/backups/` 里要恢复的那个 `ticketbox-*.db` 覆盖到 `ticketbox-data/ticketbox.db`；
3. 重新双击 EXE。

源码/家庭服务器部署的备份脚本（`backend/scripts/backup_database.ps1`、`scripts/restore_ticketbox_db.ps1`、`scripts/maintenance_ticketbox.ps1`）已改为**跟随数据根**:设了 `TICKETBOX_DATA_DIR` 用它、否则用 `backend/`,所以它们与 app 写备份的位置始终一致。诊断类脚本（`diagnose_ticketbox.ps1` 等）仍按源码 `backend/` 布局,是家庭服务器自用工具,不用于冻结 EXE。

## 冻结要点（给维护者）

- 入口 `packaging/launch.py`;spec `packaging/ticketbox-backend.spec`。
- `app/config.py`、`app/database` 用 `Path(__file__).parents[N]` 解析路径,冻结后指向 `sys._MEIPASS`(解压目录)。所以 spec 把 `alembic.ini` 和 `migrations/` 打到 **bundle 根**(`backend_root`),`static/` `templates/` 留在 `app/` 下。
- 首次启动:`init_db()` 先 `Base.metadata.create_all` 建当前 schema,再尝试用打包的 `alembic.ini` + `migrations/` 把 `alembic_version` stamp 到 head(缺这两个文件会优雅跳过,新库仍可用)。
- 动态导入(uvicorn 的 loop/protocol、`app.*` 路由、sqlite 方言)由 spec 的 `collect_submodules` + `hiddenimports` 兜底;新增依赖若运行时报 `ModuleNotFoundError`,在 spec 的 `hiddenimports` 补一行再重建。
- PyInstaller 单文件 EXE 可能触发杀软误报(无签名)。正式分发建议代码签名。

## 与 GUI 管理器的关系

`desktop/` 的后端管理器（薄进程壳 + 状态面板）当前 spawn `python -m uvicorn`;后续可让它改 spawn 这个 EXE,实现「双击即开 GUI + 后端」的一体化分发。
