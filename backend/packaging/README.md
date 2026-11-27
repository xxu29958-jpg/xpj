# 小票夹后端 · EXE / Inno 打包

把 FastAPI 后端冻结成 onedir EXE，并可进一步打成 Windows 安装器：捆绑 PostgreSQL + 后端服务，每台机器跑自己的实例（隐私优先，不共享服务器），用自己的 Android App 连。旧 ADR 及旧 release config 只是审计/兼容输入，当前发布语义以官方 Windows/SCM 合同、当前 release config 和真实目标机证据为准。

## 构建

```
cd backend
scripts\build_backend_exe.ps1          # 增量
scripts\build_backend_exe.ps1 -Clean   # 额外清理旧版共享 .venv-build
```

产物:文件夹 `backend\dist\ticketbox-backend\`(内含 `ticketbox-backend.exe` + `_internal\`;onedir,**窗口化 console=False**,ADR-0047 §8)。整个文件夹一起拷贝/分发,不能只拿出 exe。

每次构建都在 `build\` 下创建**进程私有且用后即删的精确 venv**，不复用 `.venv-build`，也不污染运行时 `.venv`。
Python、uv、PyInstaller 的精确版本只从
`packaging/windows-build-toolchain.json` 动态读取；传递依赖只从带 hash 的 `requirements-build.lock` 同步。构建会拒绝
本机版本、配置/锁、完整 Python/site-packages 执行树或冻结期间环境漂移；同一仓库的冻结构建由机器级 mutex 串行化，
只把校验通过的 staging 目录原子发布到 `dist\ticketbox-backend`，发布失败会恢复上一份完整目录。实际可执行文件 hash、
完整执行树和分发快照写入 backend provenance。该证据用于追溯，不宣称 frozen 字节可重复。
离线 OCR 随包放在 `ocr-runtime/`：独立 `ticketbox-ocr.exe`、原生库、固定 recipe、模型及字典。
默认模型由 `ocr_runtime/recipe.json` 确定，当前为官方 PP-OCRv6 tiny。检测/识别权重和字典源绑定官方仓库的精确 revision 与 SHA-256，方向分类权重来自锁定的 RapidOCR wheel；构建期获取并校验，模型许可证随包保留。字典使用规范 LF 字节。
发布前实际启动冻结 worker
识别合成票据并验证退出。运行时不安装依赖或下载模型，后端主进程不载入 OCR 原生库。

源码运行时，在安装 `requirements-ocr.txt` 后执行 `python scripts/prepare_ocr_payload.py --recipe ocr_runtime/recipe.json --output build/ocr-runtime`。已取得的匹配模型可用 `--model-root` 指定，仍须通过全部哈希校验。源码与冻结运行时都只读取已准备好的离线 bundle；更换模型通过受审查的发布配方，不依赖用户输入底层参数。

## Windows 安装器

从仓库根目录运行 `distribution/windows/build/build_installer.ps1`。它消费 frozen Backend、Manager、固定版本的 Inno 和 vendor 输入，生成 Lifecycle，编译 Setup，并发布安装器与 provenance。构建前置与 `-VerifyOnly` 的两个预期摘要见[正式构建脚本](../../distribution/windows/build/build_installer.ps1)。

旧 `build_inno_installer.ps1`、C07 原地 repair/latch、旧 runtime junction 续修和卸载 `-DeleteData` 均已被 Rev3.2 生命周期合同取代。现行 Setup 通过安装包内的 Lifecycle 执行全新安装或有界的同环境受控重建。PG 构建仍复用本目录的受保护文件操作。停机冷备、匹配 Setup、新目标和恢复后核对步骤见[Windows 数据保护手册](../../docs/runbook/WINDOWS_BACKUP_TASK.md)。

## 冻结要点（给维护者）

- 入口 `packaging/launch.py`;spec `packaging/ticketbox-backend.spec`。
- 形态:**onedir + `console=False`**(ADR-0047 §8)。`EXE(exclude_binaries=True)` + `COLLECT(...)` → `dist/ticketbox-backend/`(EXE + `_internal/`)。窗口化进程无 `sys.stdout/stderr`,所以 `launch.py` 在起 uvicorn 前用 `logging.config.dictConfig` 把 uvicorn + app 日志接到 `DATA_ROOT/logs/backend.log`(`RotatingFileHandler`),并给 uvicorn 传 `log_config=None`——否则 uvicorn 默认配置会写 `ext://sys.stdout`,`None.write` 崩。
- `app/config.py`、`app/database` 用 `Path(__file__).parents[N]` 解析路径,冻结后指向 `sys._MEIPASS`(onedir 下即 `_internal/` 目录)。所以 spec 把 `alembic.ini` 和 `migrations/` 打到 **bundle 根**(`backend_root`),`static/` `templates/` 留在 `app/` 下。
- 构建先从受控源码快照编译并哈希 `DATABASE_GENERATION_PROGRAM.json`；安装 helper、provenance、installed payload lease 与 frozen backend `init_db()` 都消费这一个 base→head 程序。该程序拥有允许执行的目标、lineage 与 revision bytes，Alembic 在 caller-owned transaction 内拥有 revision graph 执行和 `alembic_version` 状态推进；普通 backend 不拥有安装期 DDL，也不能在程序外另选 target。程序、revision bytes、lineage 或最终 revision 不一致时一律 fail closed。
- 动态导入(uvicorn 的 loop/protocol、`app.*` 路由、postgresql 方言 + psycopg 驱动)由 spec 的 `collect_submodules` + `hiddenimports` 兜底;新增依赖若运行时报 `ModuleNotFoundError`,在 spec 的 `hiddenimports` 补一行再重建。
- PyInstaller 冻结 EXE 可能触发杀软误报(无签名)。正式分发建议代码签名。
