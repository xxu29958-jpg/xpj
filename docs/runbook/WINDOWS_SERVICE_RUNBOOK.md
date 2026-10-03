# Windows 长期运行 Runbook

**当前版本：v0.9.0a1（阶段：Reports / Goals / Chart UX 收口）**

## Owner Console

后端启动后，在浏览器打开：

```
http://127.0.0.1:8000/owner
```

Owner Console 是本地中文管理后台，仅允许本机（127.0.0.1）访问，不经过 Cloudflare Tunnel。

支持操作：

- 查看服务状态、账单概要、版本信息
- 管理设备：查看 / 停用 / 重命名
- 生成 Android 绑定码（8 位，默认 15 分钟有效）
- 查看 / 新建 / 轮换 / 停用 iPhone 上传链接
- 查看 / 新建账本，并进入成员管理
- 生成家庭账本邀请、调整 member/viewer、停用成员、转让 owner、查看成员审计

UploadLink 完整 URL 只在新建或轮换时显示一次，列表只显示 `/u/***` 掩码。
家庭账本邀请明文同样只显示一次，后续列表只显示邀请状态和审计结果。

## 公网访问链路

```text
手机 / iPhone 快捷指令
  -> https://api.zen70.cn
  -> Cloudflare Tunnel
  -> Windows 本机 127.0.0.1:8000
  -> FastAPI 后端
```

手机离开家里 Wi-Fi 后仍然应该能访问 `https://api.zen70.cn`。手机和电脑不需要在同一个局域网里，真正的前提是 Windows 主机在线、没有睡眠，FastAPI 后端和 Cloudflare Tunnel 都在运行。

## 不使用的东西

本项目本地运行不需要：

- Docker
- WSL
- 路由器端口转发
- Windows 文件夹公网共享
- FastAPI 监听 `0.0.0.0`

后端继续只监听：

```text
http://127.0.0.1:8000
```

## 一次性安装自启任务

从项目根目录运行：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
```

脚本会创建或更新：

```text
TicketboxBackend
TicketboxBoundaryCheck
```

如果本机已经安装了 `cloudflared` Windows 服务，脚本会复用服务，不重复创建 Tunnel 计划任务。

如果没有 cloudflared 服务，但当前正在运行 cloudflared 进程，脚本会尝试复用当前进程的启动参数创建：

```text
TicketboxCloudflareTunnel
```

如果 `TicketboxCloudflareTunnel` 已经存在，脚本默认复用现有任务，不覆盖本机已有的 cloudflared 启动包装。

如果脚本无法推断 Tunnel 启动参数，可以显式传入：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 `
  -CloudflaredPath "C:\path\to\cloudflared.exe" `
  -CloudflaredArguments "tunnel run 你的Tunnel名"
```

只安装后端自启，不处理 Tunnel：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -SkipTunnel
```

`TicketboxBoundaryCheck` 默认在 04:00 调用 `scripts\scheduled_public_boundary_check.ps1`，跑 `check_public_boundary.ps1` 对 `PUBLIC_BASE_URL`（读 `backend\.env`）做 38 项探测。结果写到 `logs\public-boundary-<YYYY-MM-DD>.log`，默认保留 14 天。任意一条 FAIL 会让 `LastTaskResult` 变成 1，可以用 `scripts\check_windows_task_status.ps1` 抓出回归。改时间或保留天数：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 `
  -BoundaryCheckTime 04:30 -BoundaryLogRetentionDays 7
```

不想创建公网边界检查任务（例如本机没接 Cloudflare Tunnel）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -SkipBoundaryCheck
```

## 启动和停止后端

启动后端：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_backend.ps1
```

停止后端：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\stop_backend.ps1
```

`stop_backend.ps1` 默认只停止小票夹自己的 `uvicorn app.main:app` 进程。端口被其他程序占用时会拒绝停止，避免误杀无关进程。

一键重启（先停后起）：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\restart_backend.ps1
```

本机 GUI 运维壳：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\start_backend_gui.ps1
```

这个窗口只包装现有启动/停止/重启脚本，提供状态检查、打开 `/web`、打开 `/owner` 和查看最近日志；业务管理仍然在 Owner Console 和 `/web` 页面里完成。

查看 Windows 计划任务状态：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_windows_task_status.ps1
```

输出 `TicketboxBackend` / `TicketboxCloudflareTunnel` / `TicketboxBoundaryCheck` 的 `State`、`LastRunTime`、`LastTaskResult`。`0x413xx` / `2670xx` 这类 Task Scheduler 信息码（例如任务正在运行、尚未运行）不按失败处理；`TicketboxBoundaryCheck` 探测失败仍返回 `1`。

## 查看当前状态

综合检查：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_service_status.ps1
```

严格模式，适合出门前检查：

```powershell
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_service_status.ps1 -Strict
```

高级脚本会检查：

- `127.0.0.1:8000` 是否监听。
- 后端进程是谁。
- cloudflared 进程或服务是否存在。
- `TicketboxBackend` / `TicketboxCloudflareTunnel` 计划任务状态。
- 正式安装当前不提供完整数据集备份/恢复 mutation；桌面管理器只连接 CSV 导入与已确认流水导出。
- 本机 `/api/health`。
- 公网 `/api/health`。
- 公网 `/api/auth/check`（推荐使用 `TICKETBOX_SESSION_TOKEN` 环境变量，避免 token 进入命令行历史；脚本不会打印 token）。
- 最近后端日志。

更适合日常使用的一键诊断：

```powershell
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_ticketbox.ps1 -Strict
```

它会额外汇总数据库大小、待确认数量、已入账数量、最近上传时间和截图存储占用。诊断推荐使用 `TICKETBOX_SESSION_TOKEN` 环境变量传入凭证，脚本不会打印 token。UploadLink 只能上传，诊断脚本不会读取或打印 upload key。

默认诊断只输出摘要：

- 本地服务。
- 外网访问。
- Cloudflare Tunnel。
- 最近上传。
- 待确认和已入账数量。
- 数据库大小。
- 图片占用。
- 账本数量。

只有加 `-Advanced` 才显示端口、URL、cloudflared 进程、计划任务、HTTP 检查和日志尾部：

```powershell
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_ticketbox.ps1 -Advanced
```

## 按请求编号定位错误

应用日志由现有启动器写到已核对的 `TICKETBOX_DATA_DIR/logs/backend.log`，保留 5,000,000 字节轮转和三个备份。正式安装的应用数据根以服务的安装契约/绑定元数据为准；不要把源码 checkout 的 `backend/logs` 当成现用服务日志。服务包装器的 stdout/stderr 目录是安装的 `program_data_root/logs/backend`，它与应用的 `backend.log` 是不同出口。

正式安装仍由原有 SYSTEM、管理员和专用服务 SID 权限保护。获得现有读取权限的维护人员可在该目录检索响应中的 `request_id`，或任务记录的数字 ID；普通 Manager 只显示服务状态，状态诊断 ZIP 不含原始历史日志。权限不足时沿现有 Windows 管理员维护路径读取，不改 ACL，也不新增产品日志下载入口。

```powershell
$ticketboxLogDirectory = '<已核对的 TICKETBOX_DATA_DIR>\logs'
$ticketboxRequestId = '<错误响应的 request_id>'
Get-ChildItem -LiteralPath $ticketboxLogDirectory -Filter 'backend.log*' -File |
    Select-String -SimpleMatch -Pattern $ticketboxRequestId -Context 0,18
```

每条新输出含 UTC 时间（`Z`）、模块、版本及来源指纹。HTTP 行含方法、脱敏路径、状态和请求编号；任务行含任务 ID 和提交/handler/worker 外侧阶段。异常类型、机器错误码及 `at backend/...:行号 in 函数` 是异常现场，`reported_at` 是报告调用点；不包含异常原文、源码行、局部变量或 SQL 参数。日志失败不会发起业务重试，也不参与判断服务端是否已写入。

冻结包输出 `recorded_source_sha256` 和 `recorded_payload_sha256`，来自同目录既有 `BUILD_PROVENANCE.json`；用保留的该包清单/CI 构建找到对应源码。缺失清单会明确标记 `manifest_unavailable`，不可用当前主干替代发生时构建。源码运行的 `source_tree_sha256` 覆盖排序后的 `backend/app/**/*.py` 和 `backend/packaging/launch.py`（相对路径、NUL、原始字节、NUL）；它不是 Git SHA。版本号相同也不能推断来源相同。定位文件后，需要复杂度和责任导航时再查该构建对应的现有工程地图。

Android 沿既有授权的 ADB/Logcat 读取 `TicketboxNetwork`：`adb logcat -d -s TicketboxNetwork:W`。公共错误消费会保留可选请求编号，错误体优先、响应头回退；不一致时同时记录 `request_id_mismatch` 和头编号。无响应/旧响应允许没有编号。输出保留源指纹、variant、安全异常类型和项目帧；原 `Result`、cause、错误码和取消语义继续供业务使用。Logcat 不提供跨重启历史留存，本项没有增加上传或持久日志服务。

隔离合成故障可运行 `backend/tests/test_error_reporting_runtime.py` 的真实 Uvicorn 测试：它加载实际应用的完整 middleware/异常处理链，关闭 DB lifespan，仅在临时目录写日志，并验证未捕获 500、已处理 503、原表单保留、日志写入故障和轮转。它不需要触碰日常安装。后台任务的真实 PG 证据在 `test_background_tasks.py` / `test_background_task_claim.py`；Android 解析到输出由 `NetworkErrorReportingTest` 验证。

只读 `python scripts/_audit_error_reporting.py` 已接入现有 release audit 和 CI。它报告 base、资格/源码 SHA 和有限覆盖；本地未提交验证显式加 `--worktree`。新独立执行、宽捕获终止或输出边界未明确归属时返回非零。精确例外需有责任点、理由和行为测试，相关函数变化会失效；它不读取用户日志、执行业务模块或连接数据库。

## 出门前保障检查

出门前推荐运行：

```powershell
cd E:\projects\xiaopiaojia
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensure_ticketbox_runtime.ps1 `
  -ServerUrl https://api.zen70.cn
```

这条命令会尝试启动后端、启动已安装的 cloudflared 服务或计划任务，并检查公网 health；如果提供了 session token，也会检查 `/api/auth/check`。

## 手机显示网络不可用时

先在手机 Safari 打开：

```text
https://api.zen70.cn/api/health
```

应该看到：

```json
{"status":"ok"}
```

如果 Safari 也打不开，问题通常在：

- Windows 主机睡眠、关机或断网。
- Cloudflare Tunnel connector 没运行。
- 域名或 Tunnel 映射异常。
- 公司或运营商网络暂时阻断。

如果 Safari 能打开，但 App 显示网络不可用，运行：

```powershell
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_service_status.ps1 -Strict
```

再看 `backend\logs\ticketbox-backend-*.out.log` 和 `ticketbox-backend-*.err.log` 是否有异常。

后端默认关闭 Uvicorn access log，避免 UploadLink URL 中的 `upload_key` 被写入日志。因此日志里没有完整请求路径不代表请求没有到达后端，排查上传以脚本输出、pending 列表或数据库状态为准。

如果脚本或客户端返回 `401`，优先检查 session token 是否有效（是否被撤销或过期）。

如果 UploadLink 上传返回 `401`，优先检查 URL 中的 `upload_key` 是否正确。

如果返回 `legacy_auth_removed`，说明客户端仍在使用旧版 `APP_TOKEN` 或 `UPLOAD_TOKEN`，需要更新为新版凭证。

## 防止 Windows 睡眠

如果 Windows 睡眠，Cloudflare Tunnel 会断，外网也会显示网络不可用。

建议：

```text
设置 -> 系统 -> 电源和电池 -> 屏幕和睡眠
```

把接通电源时的睡眠时间调长，或者设置为不睡眠。显示器可以关闭，主机不能睡眠。

## 删除自启任务

删除小票夹创建的计划任务：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall_windows_tasks.ps1
```

删除前先停止正在运行的任务实例：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\uninstall_windows_tasks.ps1 -StopRunning
```

## 关键边界

- 不把 `uploads/` 配成公开静态目录。
- 不把 Windows 本机路径返回给手机。
- 不把 Token 写进文档、日志、截图或 Git。
- Tunnel 只映射到 `http://127.0.0.1:8000`。
- 后端只通过受保护 API 返回图片。
