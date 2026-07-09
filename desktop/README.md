# 小票夹 桌面后端管理器

一个 Windows 桌面工具,把 headless 的 FastAPI 后端「管」起来:**正式安装时控制 Windows 服务**,源码开发时监督 Uvicorn 进程,并统一展示运行/健康/地址/日志与 `/owner` 入口。管理器不重造后端管理功能,只负责主机运行态与入口。

## 启动

```
cd desktop
..\backend\.venv\Scripts\python.exe -m backend_manager
```

UI 以 Edge `--app` 无边框窗口打开(无 Edge 时回退默认浏览器)。

正式安装后,管理器从 `HKLM\Software\Ticketbox` 读取 Inno 写入的安装目录、数据目录和端口,通过 Windows SCM 控制 `TicketboxPg` / `TicketboxBackend`,并读取 `<DataRoot>\app\.env` 与 `<DataRoot>\app\logs\backend.log`。正式运行态适配器不依赖后端源码目录或 `.venv`;当前仍用 Python 启动管理器,冻结管理器 EXE 并接入安装器属于后续打包切片。

## 结构（一文件一职责）

```
backend_manager/
├── __main__.py        入口:装配 + 启动,无 import 副作用
├── config.py          从 env + 后端 .env + 发现 解析配置,URL 全 derive，零硬编码
├── installation.py    读取/校验 Inno 安装注册表,解析 Program Files / ProgramData 布局
├── runtime.py         源码进程与正式服务共用的运行态契约
├── elevation.py       固定服务动作的短命 UAC helper,高权限进程不开放 HTTP
├── windows_service.py Windows SCM 控制 + 正式数据目录日志读取
├── supervisor.py      进程生命周期:树kill 无孤儿 / health-aware 带启动宽限 / 可注入可测
├── process.py         真实 OS 原语:spawn uvicorn / taskkill /T / 健康探测
├── control_server.py  localhost HTTP 控制:token 鉴权 + Sec-Fetch-Site/Origin 检查（CSRF-safe）
├── netinfo.py         真实 LAN IPv4 发现：psutil 逐网卡枚举（绕开被 Clash 劫持的路由表）+ 过滤 CGNAT/link-local
└── ui.html            暗色 dev-tool 风状态面板
tests/                 supervisor / control-auth / config / netinfo 单测
requirements.txt       运行依赖（psutil，可选；缺失时 netinfo 降级为主机名解析）
```

## 配置（全部可 env 覆盖，默认值对齐 `scripts/start_backend.ps1`）

| 变量 | 默认 | 说明 |
|---|---|---|
| `TICKETBOX_BACKEND_ROOT` | `../backend` | 后端根目录 |
| `TICKETBOX_MANAGER_MODE` | `auto` | `auto` 优先正式安装;也可强制 `source` / `installed` |
| `TICKETBOX_BACKEND_HOST` | `127.0.0.1` | 源码模式后端 bind host |
| `TICKETBOX_BACKEND_PORT` | `8000` | 源码模式后端端口（正式模式以安装注册表为准） |
| `TICKETBOX_MANAGER_HOST` / `_PORT` | `127.0.0.1` / `8799` | 管理器自身的控制服务 |

`PUBLIC_BASE_URL`(隧道地址)从当前运行态的 `.env` 读取,与后端同源。源码模式在 `<backend>/.venv/Scripts/python.exe` 自动发现解释器;正式模式从安装注册表和 ProgramData 解析,不要求 venv。

## 设计不变量

- **无孤儿**:停止/重启走 `taskkill /T`,父+worker 一起死,端口真正释放。
- **不杀外部进程**:启动时端口上若已有健康后端(开机计划任务或上次 manager 残留的 worker),**收养**它而非 kill;只 tree-kill 自己 spawn 的进程。端口被无关进程占用时让 uvicorn bind 失败、日志暴露,绝不盲杀不属于自己的进程。
- **健康感知重启**:进程退出立即重启;父在但 `/api/health` 持续失败(过启动宽限)才重启,首启迁移不误杀。
- **服务边界清楚**:正式模式只通过 SCM 停/启后端;启动时先保证 PostgreSQL 就绪,停止后端时不顺带停库;崩溃恢复仍由安装器配置的 SCM/Shawl 策略负责。
- **GUI 永不提权**:localhost 控制服务始终以普通用户运行;每次正式服务启停只为固定动作启动短命 UAC helper,执行完立即退出。高权限进程不提供 HTTP 页面,不能被本机进程当作常驻高权限代理。
- **控制面 loopback-only**:`TICKETBOX_MANAGER_HOST` 非 loopback(`0.0.0.0` / LAN IP)会在启动前被 `config.py` 拒绝——控制服务发 token + 收控制 POST,绝不绑到公网/局域网。
- **CSRF-safe**:控制 POST 需 per-process token + 同源,跨站页面打不动。
- **零硬编码**:host/port/路径/URL 全来自 `config.py` 解析。

测试:`cd desktop && ..\backend\.venv\Scripts\python.exe -m pytest tests/`。ruff 配置复用 `backend/pyproject.toml`(`cd backend && .venv\Scripts\python.exe -m ruff check ../desktop`)。
