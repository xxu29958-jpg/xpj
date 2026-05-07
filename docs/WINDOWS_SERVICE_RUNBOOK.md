# Windows 长期运行 Runbook

小票夹的公网访问链路是：

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

## 查看当前状态

综合检查：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_service_status.ps1
```

严格模式，适合出门前检查：

```powershell
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
- 公网 `/api/auth/check`，Token 从 `backend\.env` 读取但不会打印。
- 最近后端访问日志。

更适合日常使用的一键诊断：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_ticketbox.ps1 -Strict
```

它会额外汇总数据库大小、待确认数量、已入账数量、最近上传时间、截图存储占用和上传口令检查。脚本读取本机 `backend\.env`，但不会打印 Token。

默认诊断只输出摘要：

- 本地服务。
- 外网访问。
- Cloudflare Tunnel。
- 最近上传。
- 待确认和已入账数量。
- 数据库大小。
- 图片占用。
- 租户数量。

只有加 `-Advanced` 才显示端口、URL、cloudflared 进程、计划任务、HTTP 检查和日志尾部：

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\diagnose_ticketbox.ps1 -Advanced
```

## 出门前保障检查

出门前推荐运行：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\ensure_ticketbox_runtime.ps1 `
  -ServerUrl https://api.zen70.cn
```

这条命令会尝试启动后端、启动已安装的 cloudflared 服务或计划任务，并检查公网 health/auth。

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
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_service_status.ps1 -Strict
```

再看 `backend\logs\ticketbox-backend-*.out.log` 是否有 App 对应接口请求。

如果日志里没有新请求，说明请求没有到达后端，优先查手机网络、域名、Cloudflare Tunnel 或 App 配置。

如果日志里有请求但状态码是 `401`，优先查 `APP_TOKEN`。

如果日志里有上传请求但返回 `401`，优先查 iOS 快捷指令的 `Upload-Token`。

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
