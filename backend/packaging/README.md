# 小票夹后端 · EXE / Inno 打包

把 FastAPI 后端冻结成 onedir EXE,并可进一步打成 ADR-0047 的 Windows 安装器:捆绑 PostgreSQL + 后端服务,每台机器跑自己的实例(隐私优先,不共享服务器),用自己的 Android App 连。

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
完整执行树和分发快照写入 backend provenance。该证据用于追溯，不宣称 frozen 字节可重复。**不含 OCR**
(rapidocr/onnxruntime/opencv 太重且可选)——需要 OCR 的话另装 `requirements-ocr.txt` 跑源码版。

## 档 B:Inno 捆绑安装器(ADR-0047)

档 B 是正式分发路线:安装器把程序放进 `C:\Program Files\Ticketbox`,把数据放进 `C:\ProgramData\Ticketbox`,并注册两个 Windows 服务:

| 服务 | 账户 | 说明 |
|---|---|---|
| `TicketboxPg` | `NT SERVICE\TicketboxPg` | 捆绑 PostgreSQL 17,簇在 `...\pgdata` |
| `TicketboxBackend` | `NT SERVICE\TicketboxBackend` | Shawl 包 frozen backend,依赖 `TicketboxPg` |

构建前置:

1. 已生成 frozen backend:`backend\dist\ticketbox-backend\ticketbox-backend.exe`。
2. 已裁出捆绑 PG:`backend\packaging\vendor\pg\bin\pg_ctl.exe`。
3. 已放好 Shawl:`backend\packaging\vendor\shawl\shawl.exe`。
4. 构建机安装 Inno Setup 6,或用 `-InnoCompiler` 指定 `ISCC.exe`。
5. 仓库内置 Inno 简体中文语言文件:`backend\packaging\languages\ChineseSimplified.isl`。

命令:

```
cd backend
packaging\build_inno_installer.ps1 -CheckInputsOnly   # 无 Inno 时只校验输入
packaging\build_inno_installer.ps1                    # 原子发布完整版本目录
```

安装包版本只能从 `app/version.py` 的 `BACKEND_VERSION` 动态读取；构建工具版本只能从
`packaging/windows-build-toolchain.json` 读取；服务/数据库身份、默认/隔离端口、SCM 策略、
就绪等待、bootstrap 默认值和密钥强度只能从 `packaging/windows-release-config.json` 读取。构建脚本只把向导所需值
注入 Inno，升级预检、安装和卸载则通过 `windows_release_config.ps1` 读取并校验配置，不再从 Inno 重复传递服务名或
超时。覆盖升级在复制前读取已安装的 N-1 config 校验旧服务，并把该已验证配置保存到 Inno 临时快照，复制后仍用 N-1
策略完成旧服务删除，注册后才以 N config 验证新服务；服务名、数据库名和数据库角色
属于持久身份，变化必须有显式迁移，不能伪装成普通策略更新。`build_inno_installer.ps1` 是受支持的构建入口：它绑定实际
ISCC defines，编译后重新读取 backend/PG/Shawl/recipe/Git/ISCC 证据，再把 EXE、SHA-256 旁车、provenance 和完成标记作为
一个 staging 单元验证并原子发布到 `dist\installer\Ticketbox-Setup-<version>\`；并发构建由同一机器级构建锁串行化，替换失败
会恢复上一份完整发布单元。普通方式直接调用
`.iss` 不提供这些必需 defines/provenance，会被脚本的常规入口契约拒绝；该约束不是对任意本机管理员的密码学防篡改声明。

安装行为:

- 安装包使用小票夹图标和“小票夹后端服务”显示名,开始菜单会创建“打开小票夹 Web”和“数据目录”快捷方式。
- 安装器标准页面和按钮使用内置简体中文语言文件;自定义数据目录/端口页面也保持中文。
- 安装器只有一套脚本与配置真源,并同时兼容 Windows PowerShell 5.1 / PowerShell 7 两种宿主:只从 HKLM PowerShell Core 安装记录动态发现位于受保护 Program Files 且 Microsoft 签名有效的机器级 `pwsh.exe`;用户目录中的执行别名不会被提权运行。没有可信 PS7 时自动回退系统自带 5.1,普通用户无需额外安装运行时。
- 安装向导会先让用户确认程序目录、数据目录和本机服务端口;若默认 `5432/8000` 被占用,会自动预填开发机常用隔离端口 `5440/8001`,也可以在界面中改成其它空闲端口。
- 首次安装默认使用 `C:\ProgramData\Ticketbox\pgdata` + `C:\ProgramData\Ticketbox\app`。
- `app\.env` 由脚本写成 UTF-8 no BOM,`DATABASE_URL` 指向配置中动态读取的应用角色；上传大小、OCR、API 文档等应用默认值继续由后端 `config.py` 单源负责，安装器不复制一份。
- 覆盖升级会在 Inno **复制新程序文件之前**按 Windows 原生命令行规则校验两个同名服务的完整 argv、虚拟服务账户和动态路径：PG 不允许额外 `-o`，Shawl 的 name/dependency/cwd/log/env/timeout/restart/payload 必须与已安装 N-1 配置逐项一致且不得出现未知或重复参数。随后停止后端，确认 loopback `DATABASE_URL` 同时命中预期 PG 端口、数据库、角色、非空口令和数据根，使用旧版本工具生成 `pg_dump -Fc` 并以 `pg_restore --list` 校验，最后停止 PostgreSQL。`psql -X -w` / `pg_dump --no-password` 禁止用户启动脚本或交互取密；口令只通过临时 `PGPASSWORD` 传入，含应用角色口令的建库 SQL 只走标准输入，不进入进程命令行或异常文本。快照写入服务账户无权删除的 `installer-backups\ticketbox-pre-upgrade-installer-*.dump`；任一步失败都会在旧文件仍完整时恢复原服务运行态并中止升级。
- 若旧版本已经卸载服务和 HKLM 安装登记、但明确保留了 ProgramData，修复安装只接受受保护 ACL、无 reparse、目标 PG major 匹配、可信 version floor 且 `.env` 指向所选本机数据库的 legacy 布局。常态 version floor 来自持久安装身份；从尚未生成该身份的旧安装首次升级时，只允许稳定 AppId、产品名、HKLM DataRoot/InstallDir 和 Inno DisplayVersion 全部互相绑定的一次性迁移，孤儿数据继续 fail closed。目标 PG 工具复制完成后，安装器先在回执记录清理义务，再以配置中的正式 PG 服务名注册 demand-start SCM 服务，并在 `NT SERVICE\<pg_service_name>` 虚拟账户下启动精确 DataRoot；连接的数据根/端口和 `pg_dump` 通过后精确停删服务，才允许推进回执。断电后的下一次修复也必须先完成该清理；备份提交前不执行建表、业务迁移或 DataRoot ACL 收编。
- Inno 从启动到复制、服务后置配置和卸载全程持有 `{commoncf64}\Ticketbox\installer-lifecycle.lock`，并动态写入受保护的持锁进程记录。子 PowerShell 必须是记录中持锁进程的直接子进程、确认零共享锁仍被占用且运行在 64 位宿主中，才可复用安装器总锁；独立服务脚本则动态读取 OS `CommonProgramFiles` 并自行持有同一文件。锁目录、锁文件和 owner 记录为 SYSTEM owner 且仅 SYSTEM/Administrators 可访问，低权限进程不能预创建、只读抢占或靠重放开关绕过串行化。
- 服务 argv 归属在 `windows_service_contract.ps1`，SCM 终态控制在 `windows_service_lifecycle.ps1`，机器级独占锁在 `windows_lifecycle_lock.ps1`；loopback libpq、口令隔离、数据库数据根和 dump 防护归属在 `windows_database_safety.ps1`，后端 deadline 就绪与首次 owner 创建归属在 `windows_backend_bootstrap.ps1`，监听器暴露后的停服轮换归属在 `windows_bootstrap_exposure_recovery.ps1`，路径/ACL/marker/删除边界归属在 `windows_installation_safety.ps1`。安装、升级、桌面 GUI 的服务控制和卸载都争用同一把机器锁；GUI 每次变更 SCM 前还会动态读取安装注册表中的服务名，并通过已安装的 `install_bundled_services.ps1 -ValidateInstalledServicesOnly` 复核 release config、ImagePath、虚拟账户、依赖、Shawl payload 与启动策略。各入口按动态策略与单调时钟 deadline 等待稳定态及 `running` / `stopped` / `absent`，服务记录缺失时也继续按登记端口和安装路径扫描孤儿进程。
- frozen backend 目录下本机运行生成的 `ticketbox-data\` 会从 Inno 输入中整目录排除,避免把开发机日志、配置或上传文件带进发布包。
- 数据根写 marker 前会拒绝根或任一祖先 junction/reparse point 并转 SYSTEM owner。根目录只给服务账户非继承 ReadExecute，PG/后端 FullControl 分别限制在 `pgdata` / `app` 子树，避免任一服务借父目录 `DELETE_CHILD` 删除兄弟目录；直接脚本升级在备份前就应用该拓扑，不会先给两服务跨树 FullControl。安装成功还会原子写入仅 SYSTEM/Administrators 可读的持久安装身份，绑定 version floor、installation id、build manifest hash、路径、服务和端口；仅剩 PG 数据但该身份与旧安装证据都不可信时 fail closed。legacy 子项会递归重置 owner/显式 ACL；`initdb` 口令文件删不掉或删除后仍存在时安装立即中止，不会进入后端 ACL/启动阶段。
- 首次安装会通过一次性 HTTP bootstrap 创建 owner,凭证写入仅 SYSTEM/Administrators 可读的 `app\owner-bootstrap.txt`,随后从 `.env` 清掉 bootstrap 开关。每一代 HTTP listener 一旦暴露，安装流程都会先原子写入同 ACL 的 guard/intent 并把 `.env` 切到无 secret 隔离态，之后才停服、离线轮换确定性凭据并撤销暴露窗口内增发的 token/link/device；停服失败也保留隔离证据。若 8 位 replacement pairing code 与历史记录碰撞，后端在任何凭证变更前返回专用内部结果，PowerShell 原子换代 replacement secret 后重试。维护失败还会原子留下不含 secret 的 `bootstrap-exposure-recovery-result.json`，父 PowerShell 只读取受保护、大小受限、schema/operation id 匹配的诊断结果。owner handoff v2 同时绑定 InstallDir、DataRoot、凭据文件 hash、安装进程 PID 与进程启动时间：活的原 owner 不能被另一安装器接管，原 owner 崩溃后只能由持有生命周期锁的修复安装重绑；Inno 以 UTF-8 读取并在完成页真正展示一次绑定信息后才清除，避免晚失败永久跳过交付，也不把 token 放进命令行、日志或宽权限临时目录。
- 卸载默认只删除归属校验通过的服务和程序文件，**保留 ProgramData 数据**。卸载前同时核对 SCM 稳定态与 `pg_ctl status -D`，服务/数据簇进程不一致即失败；删除 PG 服务前再次确认数据簇已停。手动 `-DeleteData` 还必须通过注册表 DataRoot、安装专属 JSON marker 和无重解析点检查。

当前升级边界:复制新文件前的失败可恢复旧服务状态;新文件复制已经开始后的二进制/schema 自动回滚尚未宣称完成。此时可验证数据库快照仍保留,但版本化程序目录、自动恢复和真实故障注入属于后续原子升级切片,不能用“`pg_restore --list` 通过”代替。

高级命令行参数仍可用于自动化安装(传给安装器 EXE):

```
Ticketbox-Setup-<version>.exe /TicketboxDataRoot="D:\TicketboxData" /TicketboxBackendPort=8000 /TicketboxPgPort=5432
```

开发机若已有本机 PostgreSQL/源码后端占用默认 `5432/8000`,直接双击安装器即可在“服务端口”页面看到自动预填的 `5440/8001`。安装器会在正式复制文件前检测所选端口;若端口已被占用,会停在向导页提示换端口,避免复制文件后后置服务脚本失败。

注意:当前发布工程明确不做代码签名,Windows SmartScreen 可能提示未知发布者;发布验收只保留未签名安装器的 SmartScreen walkthrough。

## 档 A:本机 PostgreSQL 一键安装(legacy)

已装好 PostgreSQL 后,把 `ticketbox-backend\` 文件夹、`install_ticketbox.ps1`、
`windows-release-config.json`、`windows_release_config.ps1`、
`windows_installation_safety.ps1`、`windows_lifecycle_lock.ps1` 和
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
# 非交互模式:-NonInteractive
#             -PostgresSuperPasswordFile <受保护的一次性超级用户口令文件>
# 既有角色重跑时再加:
#             -PostgresRolePasswordFile <受保护的一次性应用角色口令文件>
```

交互模式会用安全输入框询问口令。非交互密码文件必须是单行 UTF-8、关闭 ACL 继承，
且只允许当前用户、`SYSTEM` 或 `Administrators` 读取；脚本读取后会验证删除。不要把
数据库口令直接放进命令行、批处理参数或 CI 日志。

红线:建角色/建库才用超级用户,**建表只能由应用角色连接**;`.env` 不带 BOM;不依赖
Docker/WSL/PS7。档 A 仍假设本机已装 PostgreSQL 服务,主要用于老用户/开发机临时安装;新分发优先用上面的档 B。

## 运行与数据

双击 `ticketbox-backend\ticketbox-backend.exe`,默认监听 `127.0.0.1:8000`(窗口化,不弹控制台窗口)。

档 A/直接双击时,所有**可写数据**放在 EXE 旁的 `ticketbox-data/`(onedir 程序文件夹内、与 `_internal\` 同级;冻结的 bundle 本身只读/临时):

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

档 B/服务安装器会通过 Shawl 设置 `TICKETBOX_DATA_DIR=C:\ProgramData\Ticketbox\app`,所以同一套 `launch.py` 会把 `.env`、uploads、logs、backups 都落在 ProgramData,不会写入 Program Files。

`launch.py` 在 import `app.*` 之前把 `UPLOAD_DIR` 指向数据目录、并把 uvicorn + app 日志配到 `logs/backend.log`(windowed `console=False` 无 stdout,改写文件);若存在 `<data>\.env` 则**优先**采用其中的值(`override=True`)。`DATABASE_URL` 不在这里默认——后端是 PostgreSQL-only,要么在 `.env` 里设、要么回落到 `app.config` 的本机 PostgreSQL 默认(EXE 假设本机已装 PostgreSQL 服务)。

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

`desktop/` 的后端管理器已支持两种运行态:源码模式继续监督 `python -m uvicorn`;检测到 `HKLM\Software\Ticketbox` 后切到正式安装模式,通过 Windows SCM 管理 `TicketboxPg` / `TicketboxBackend`,并从 ProgramData 读取配置和日志。把管理器冻结成 EXE 并纳入 Inno 仍是下一打包切片。
