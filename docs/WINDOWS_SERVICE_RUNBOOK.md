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
- 生成 Android 绑定码（6 位，默认 15 分钟有效）
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
TicketboxBackup
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

只安装后端和 Tunnel，不创建每日 SQLite 备份任务：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -SkipBackup
```

每日备份默认保留 30 天。调整保留天数：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1 -BackupRetentionDays 14
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

输出 `TicketboxBackend` / `TicketboxCloudflareTunnel` / `TicketboxBackup` 的 `State`、`LastRunTime`、`LastTaskResult`。

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
- `TicketboxBackup` 每日 SQLite 备份任务状态。
- 本机 `/api/health`。
- 公网 `/api/health`。
- 公网 `/api/auth/check`（使用 `-SessionToken` 或 `TICKETBOX_SESSION_TOKEN`，不会打印 token）。
- 最近后端日志。

更适合日常使用的一键诊断：

```powershell
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_ticketbox.ps1 -Strict
```

它会额外汇总数据库大小、待确认数量、已入账数量、最近上传时间和截图存储占用。脚本使用 `-SessionToken` 或 `TICKETBOX_SESSION_TOKEN`，但不会打印 token。UploadLink 只能上传，诊断脚本不会读取或打印 upload key。

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
