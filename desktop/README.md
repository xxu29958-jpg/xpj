# 小票夹 桌面后端管理器

一个 Windows 桌面工具,把 headless 的 FastAPI 后端「管」起来:**监督进程**(独占、崩溃自动重启、树 kill 杜绝孤儿 worker)+ **可视状态**(运行/健康/地址/日志)+ 一键打开后端已有的 `/owner` 管理台。仿 SyncTrayzor 模式:不重造后端的管理功能,只做进程壳。

## 启动

```
cd desktop
..\backend\.venv\Scripts\python.exe -m backend_manager
```

UI 以 Edge `--app` 无边框窗口打开(无 Edge 时回退默认浏览器)。

## 结构（一文件一职责）

```
backend_manager/
├── __main__.py        入口:装配 + 启动,无 import 副作用
├── config.py          从 env + 后端 .env + 发现 解析配置,URL 全 derive，零硬编码
├── supervisor.py      进程生命周期:树kill 无孤儿 / health-aware 带启动宽限 / 可注入可测
├── process.py         真实 OS 原语:spawn uvicorn / taskkill /T / 清端口 / 健康探测
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
| `TICKETBOX_BACKEND_HOST` | `127.0.0.1` | 后端 bind host |
| `TICKETBOX_BACKEND_PORT` | `8000` | 后端端口（所有 URL 由它 derive） |
| `TICKETBOX_MANAGER_HOST` / `_PORT` | `127.0.0.1` / `8799` | 管理器自身的控制服务 |

`PUBLIC_BASE_URL`(隧道地址)从后端 `.env` 读取,与后端同源。venv 解释器在 `<backend>/.venv/Scripts/python.exe` 自动发现。

## 设计不变量

- **无孤儿**:停止/重启走 `taskkill /T`,父+worker 一起死,端口真正释放。
- **不杀外部进程**:启动时端口上若已有健康后端(开机计划任务或上次 manager 残留的 worker),**收养**它而非 kill;只 tree-kill 自己 spawn 的进程。端口被无关进程占用时让 uvicorn bind 失败、日志暴露,绝不盲杀不属于自己的进程。
- **健康感知重启**:进程退出立即重启;父在但 `/api/health` 持续失败(过启动宽限)才重启,首启迁移不误杀。
- **控制面 loopback-only**:`TICKETBOX_MANAGER_HOST` 非 loopback(`0.0.0.0` / LAN IP)会在启动前被 `config.py` 拒绝——控制服务发 token + 收控制 POST,绝不绑到公网/局域网。
- **CSRF-safe**:控制 POST 需 per-process token + 同源,跨站页面打不动。
- **零硬编码**:host/port/路径/URL 全来自 `config.py` 解析。

测试:`cd desktop && ..\backend\.venv\Scripts\python.exe -m pytest tests/`。ruff 配置复用 `backend/pyproject.toml`(`cd backend && .venv\Scripts\python.exe -m ruff check ../desktop`)。
