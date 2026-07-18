# 小票夹 桌面后端管理器

一个 Windows 桌面入口，把 headless 的 FastAPI 后端变成普通用户可操作的本机产品。它包含两个边界明确的表面：

- **小票夹桌面工作区**：开始菜单默认打开 Manager 同源 `/web`，通过受限 BFF 复用完整 Web 产品；旧 `/app` 壳仅用于未绑定或后端故障恢复，不再承载独立账务真值。
- **小票夹管理器**：只负责正式安装态的 Windows 服务控制，或源码态的 Uvicorn 监督，并提供设备连接、备份、系统体检和脱敏诊断包入口。它不读取数据库、不复制账务状态，也不重造后端业务。

## 启动

```
cd desktop
..\backend\.venv\Scripts\python.exe -m backend_manager
```

UI 只以 HKLM App Paths 动态发现并校验的 Edge `--app` 窗口打开；每个 app-window 使用独立且不含秘密的 profile，并通过 Edge 直启参数持有真实、可等待的浏览器进程，最后一个窗口关闭后 Manager 主进程退出。无合格 Edge 时 fail closed。默认窗口读取当前用户 ACL 限定的临时 bootstrap HTML，以 POST body 提交独立单次 token，建立 HttpOnly Manager 会话后进入干净 `/web`；临时文件在消费或关闭时删除，instance proof、app token 与 control token 均不进入 URL、Edge 参数或浏览器脚本。

Manager BFF 只连接 `127.0.0.1`，从 WinCred 临时读取既有 app identity，在进程内注入 Bearer 与固定 `X-Ticketbox-Desktop-Bridge: v1`。它只代理 `/web/**`、Web/shared 静态资源和精确的 `PUT /api/me/ui-preferences` 主题写入，其他 `/api/**`、`/owner`、`/desktop`、认证页及歧义路径全部拒绝；客户端敏感/转发头不会进入后端。Manager 不读数据库、不 iframe `/web`，也不复制账务真值。

| 工作区 | 当前真实数据 |
| --- | --- |
| 收件 | 当前账本真实 `pending` 票据 |
| 流水 | 当前账本真实 `confirmed` 流水，首屏最多 200 行 |
| 往来 | 当前账本欠款折叠后的本金、已清算和剩余金额 |
| 计划 | 当前月预算、支出目标、收入计划和固定支出 |
| 洞察 | 当前月报表概览和数据质量指标 |

### 桌面产品交互合同

- 产品壳支持 `1180×760` 默认窗口和 `820×660` 紧凑窗口。导航序号、任务说明、状态说明、快捷键等辅助文字的计算字号不得低于 `12px`；两种窗口下都不得出现横向溢出、按钮裁切或无可访问名称的交互控件。
- `Alt+1` 至 `Alt+5` 只切换产品壳一级工作区，方向键 / `Home` / `End` 选择中央表格行，`Ctrl+R` 或 `F5` 在同窗重新取数，`/` 聚焦表格筛选；`Alt+0` 始终进入原有管理器。
- 日常业务入口只在后端明确投影 `product_available=true` 时开放。服务停止、安装维护未完成或拥有者身份需恢复时，业务入口 fail closed，但状态卡必须就地提供「打开系统管理」主操作。
- 「打开系统管理」与左下角「系统管理与备份」必须指向同一个携带当前 instance challenge 的管理器地址。产品壳不直接调用服务启停 API；启动、停止、诊断和修复仍归管理器及其既有权限边界。

正式安装后，管理器从 `HKLM\Software\Ticketbox` 动态读取 Inno 写入的安装布局和服务合同，通过 Windows SCM 的只读投影查看状态；启停只调用安装目录中受保护 `ticketbox-manager.exe` 的固定动作短命 UAC helper，当前源码树或复制到用户目录的 Manager 不会被提升。普通用户进程不读取受保护的 `.env`、数据库或后端原始日志。正式运行态不依赖源码目录、Python 或 `.venv`。

若 HKLM 登记或 release config 已损坏，冻结 Manager 不伪造服务配置，也不回退源码模式；它只从相邻构建 manifest 取得当前版本并进入受限维护壳。此时 SCM 与 Owner 动作全部禁用，只保留脱敏诊断导出，并提示用户手动使用可信安装包维护。

正式 EXE 构建：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File desktop\scripts\build_manager_exe.ps1 -Clean
```

输出是 `desktop\dist\ticketbox-manager\ticketbox-manager.exe` 与同目录 `BUILD_PROVENANCE.json`。Inno 构建会验证该 manifest 与当前 Manager 源码、版本和 payload hash 一致，再把整份 onedir 安装到 `{app}\manager` 并创建开始菜单入口。安装器不自动拉起 GUI：右键以管理员身份启动 Setup 时，Windows 无法安全恢复原登录用户上下文；完成页会明确提示从开始菜单打开。覆盖安装只有在生命周期预检、停服和升级前备份成功后，才先清空旧 Manager payload 再复制新 onedir，避免 N-1 独有 DLL/PYD 留在运行目录形成混合版本；真实 N-1 升级仍以 clean-machine E2E 为发布资格证据。

## 结构（一文件一职责）

```
backend_manager/
├── __main__.py        入口:装配 + 启动,无 import 副作用
├── build_identity.py  冻结 Manager 相邻 manifest 的最小版本身份
├── config.py          从 env + 后端 .env + 发现 解析配置,URL 全 derive，零硬编码
├── installation.py    读取/校验 Inno 安装注册表,解析 Program Files / ProgramData 布局
├── runtime.py         源码进程与正式服务共用的运行态契约
├── elevation.py       固定服务动作的短命 UAC helper,高权限进程不开放 HTTP
├── windows_service.py Windows SCM 控制 + 服务/安装身份脱敏诊断
├── diagnostic_bundle.py 只按 allowlist 导出脱敏主机/构建证据
├── supervisor.py      进程生命周期:树kill 无孤儿 / health-aware 带启动宽限 / 可注入可测
├── process.py         真实 OS 原语:spawn uvicorn / taskkill /T / 健康探测
├── manager_startup.py 单实例 owner、窗口进程集合与宿主退出状态机
├── desktop_shell.py   HKLM Edge 发现、独立 app profile 与可等待窗口进程
├── maintenance_gate.py 只读验证 HKLM 安装维护 owner 记录和进程身份
├── control_server.py  localhost HTTP 控制:token 鉴权 + authenticated reopen + 产品桥
├── product_data.py    allowlist 本机后端投影/命令客户端；无业务凭证、禁代理/重定向
├── netinfo.py         真实 LAN IPv4 发现：psutil 逐网卡枚举（绕开被 Clash 劫持的路由表）+ 过滤 CGNAT/link-local
├── product.html       持久五域同窗业务 GUI；中央表格 + 自适应右侧 inspector / 小窗抽屉
└── ui.html            服务 / 连接 / 备份升级 / 自救维护台
tests/                 supervisor / control-auth / config / netinfo 单测
requirements.txt       运行依赖（psutil，可选；缺失时 netinfo 降级为主机名解析）
requirements-build.*   Manager 冻结构建的精确依赖输入与 hash lock
packaging/             独立 PyInstaller onedir spec
scripts/               Manager provenance 与冻结构建入口
```

## 配置（全部可 env 覆盖，默认值对齐 `scripts/start_backend.ps1`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `TICKETBOX_BACKEND_ROOT` | `../backend` | 后端根目录 |
| `TICKETBOX_MANAGER_MODE` | `auto` | `auto` 优先正式安装;也可强制 `source` / `installed` |
| `TICKETBOX_BACKEND_HOST` | `127.0.0.1` | 源码模式后端 bind host |
| `TICKETBOX_BACKEND_PORT` | `8000` | 源码模式后端端口（正式模式以安装注册表为准） |
| `TICKETBOX_MANAGER_HOST` / `_PORT` | `127.0.0.1` / `8799` | 管理器自身的控制服务 |

`PUBLIC_BASE_URL`（隧道地址）从当前 `TICKETBOX_DATA_DIR/.env` 读取，与后端同源。源码模式在 `<backend>/.venv/Scripts/python.exe` 自动发现解释器；相对 `TICKETBOX_DATA_DIR` 永远相对该 backend root 解析一次。源码 bind host 只接受 `127.0.0.1`、`localhost` 或 `0.0.0.0`，Manager 健康探测固定走 `127.0.0.1`。正式模式从安装注册表和 ProgramData 解析，不要求 venv。

## 设计不变量

- **无孤儿**:停止/重启走 `taskkill /T`,父+worker 一起死,端口真正释放。
- **不杀外部进程**:启动时端口上若已有健康后端(开机计划任务或上次 manager 残留的 worker),**收养**它而非 kill;只 tree-kill 自己 spawn 的进程。端口被无关进程占用时让 uvicorn bind 失败、日志暴露,绝不盲杀不属于自己的进程。
- **健康感知重启**:进程退出立即重启;父在但 `/api/health` 持续失败(过启动宽限)才重启,首启迁移不误杀。
- **服务边界清楚**:正式模式只通过 SCM 停/启后端;启动时先保证 PostgreSQL 就绪,停止后端时不顺带停库;崩溃恢复仍由安装器配置的 SCM/Shawl 策略负责。
- **GUI 生命周期不接管服务**:正式模式关闭最后一个 Edge 窗口只退出 Manager 主进程和本机控制面,不停止 SCM 服务;源码模式只清理自己创建的开发后端。
- **单实例仍完整持窗**:第二次启动先用 challenge/HMAC 识别既有 owner,再让 owner 通过 authenticated reopen 创建和登记新窗口;第二个进程不直接留下无人跟踪的 Edge。
- **业务权威不进 GUI**：绑定码、设备、UploadLink、备份与业务诊断仍由 loopback `/owner` 和后端服务生成；Manager 只打开精确任务页，不读取或写入数据库。
- **GUI 永不提权**:localhost 控制服务始终以普通用户运行;每次正式服务启停只为固定动作启动短命 UAC helper,执行完立即退出。高权限进程不提供 HTTP 页面,不能被本机进程当作常驻高权限代理。
- **控制面 loopback-only**:`TICKETBOX_MANAGER_HOST` 非 loopback(`0.0.0.0` / LAN IP)会在启动前被 `config.py` 拒绝——控制服务发 token + 收控制 POST,绝不绑到公网/局域网。
- **CSRF-safe**:控制 POST 需 per-process token + 同源,跨站页面打不动。
- **重绑定两阶段提交**：后端先签发 5 分钟、不能用于普通请求的 pending B；Manager 必须先把 B 持久写入 WinCred recovery 位，再调用 activation，在同一服务端事务中激活 B 并精确撤销仍有效的 Desktop A，最后把 B 提升到 primary。activation 响应丢失、Manager crash 或 primary 写入失败都可从 recovery 幂等重放；recovery 写入失败时不会激活 B。若本地 A 已丢失，不按设备名猜测撤销未知会话，用户需在 Owner Console 精确撤销旧设备。
- **诊断默认脱敏**：一键导出的 ZIP 只含 allowlist 服务状态、OS 版本和构建摘要；不含 token、数据库内容、原始日志、LAN/公网 URL 或数据绝对路径。
- **升级权威仍归安装器**：未建立签名发行链前，Manager 不自动选择或提权运行安装包。外部安装、升级和卸载通过绑定生命周期锁 owner 的 HKLM 维护记录回收 Manager 窗口；崩溃残留按 PID 与进程创建时间识别，不会永久阻塞。
- **零硬编码**:host/port/路径/URL 全来自 `config.py` 解析。

测试：`cd desktop && ..\backend\.venv\Scripts\python.exe -m pytest tests/`。Windows 测试会通过本机 Edge DevTools 协议真实渲染 320 / 390 / 480 小窗与 820×660 / 1180×760 支持窗口，检查主舞台宽度、详情抽屉焦点闭环、overflow、控件交叠和可访问名称；还会直接调用生产 `open_app_window()` 验证用户关窗后进程退出，以及页面完全不响应时宿主仍能终止并回收 Edge。缺少 Edge 会使 Windows 门禁失败而不是静默跳过。ruff 配置复用 `desktop/pyproject.toml`。
