# Cloudflare Tunnel 配置说明

小票夹后端默认只监听：

```text
http://127.0.0.1:8000
```

Cloudflare Tunnel 只负责把公网 HTTPS 域名转发到这个本机地址：

```text
https://api.你的域名.com -> http://127.0.0.1:8000
```

不要开放路由器端口，不要把 `uploads/` 暴露成静态目录，不要把 FastAPI 改成监听 `0.0.0.0`。

## MCP 状态

如果当前 Codex 会话暴露了 Cloudflare MCP 工具，可以用 MCP 查询账号、Zone、Tunnel 和 DNS 记录。

如果工具没有暴露，但 Cloudflare 插件已经安装，通常需要重开或刷新 Codex 会话后工具才会出现在工具注册表里。没有 MCP 时，仍然可以按本文档和脚本完成本机验收。

当前项目不把 Cloudflare Token、Tunnel Token 或账号凭据写入仓库。

## 推荐 Dashboard 配置

在 Cloudflare Zero Trust 控制台：

1. 进入 `Networks` -> `Tunnels`。
2. 创建 Cloudflared Tunnel。
3. Public hostname 填：

```text
api.你的域名.com
```

4. Service 类型选 `HTTP`，URL 填：

```text
127.0.0.1:8000
```

5. 保存后按 Cloudflare 提供的命令在 Windows 上运行 connector。

## 本机后端检查

启动后端：

```bat
cd /d E:\projects\xiaopiaojia\backend
run.bat
```

本机健康检查：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

## 公网入口检查

Tunnel 配好后，从项目根目录运行：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\check_cloudflare_endpoint.ps1
```

项目默认检查：

```text
https://api.zen70.cn
```

也可以显式指定：

```powershell
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
$env:TICKETBOX_UPLOAD_LINK="/u/<upload_key>?tz=Asia/Shanghai"
powershell -ExecutionPolicy Bypass -File scripts\check_cloudflare_endpoint.ps1 `
  -ServerUrl https://api.zen70.cn
```

脚本会：

- 检查 `/api/health`。
- 检查 `/api/auth/check`（使用 session token）。
- 用 UploadLink URL 测试上传。

> **注意**：v0.3 以后脚本不再从 `backend\.env` 读取旧 `APP_TOKEN`/`UPLOAD_TOKEN`。需要通过 `-SessionToken` / `-UploadLink` 参数，或 `TICKETBOX_SESSION_TOKEN` / `TICKETBOX_UPLOAD_LINK` 环境变量传入当前有效凭证。`UploadLink` 可以是完整 URL，也可以是 `/u/<upload_key>?tz=...` 路径。

当前 Windows 联调推荐同时启用两个登录自启任务：

```powershell
cd E:\projects\xiaopiaojia
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\install_windows_tasks.ps1
```

其中：

- `TicketboxBackend` 启动本机 FastAPI：`127.0.0.1:8000`。
- `TicketboxCloudflareTunnel` 启动 Cloudflare Tunnel connector。

查看任务状态：

```powershell
Get-ScheduledTask -TaskName TicketboxBackend,TicketboxCloudflareTunnel
```

更完整的长期运行流程见 [Windows 长期运行 Runbook](WINDOWS_SERVICE_RUNBOOK.md)。

只检查健康和 session token，不上传测试图：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_cloudflare_endpoint.ps1 `
  -ServerUrl https://api.你的域名.com `
  -SessionToken "<session_token>" `
  -SkipUpload
```

## iPhone 快捷指令 URL

v0.3 快捷指令使用 UploadLink URL，不再使用旧版 `Upload-Token` header：

```text
https://api.你的域名.com/u/<upload_key>?tz=Asia/Shanghai
```

请求头：

```text
User-Agent: TicketBox/1.0 iOS-Shortcut
```

请求体：

```text
文件
文件值：转换后的图像
```

建议在快捷指令里先转换为 JPEG 或 PNG。iOS 26.4 实测应使用"文件"请求正文，不要使用"表单"请求正文。

旧快捷指令如果使用旧版 `/api/upload-screenshot` 和 `Upload-Token` header，后端会返回 `legacy_auth_removed`。

## Android 绑定地址

Android App 首次绑定服务器地址：

```text
https://api.你的域名.com
```

绑定码（Pairing Code）：

```text
服务拥有者提供的 8 位数字
```

> **注意**：v0.3 不再使用旧版 `APP_TOKEN`。Android 绑定需要服务器地址 + 8 位绑定码。

灰度用户版绑定后只查看账本连接状态；内部联调版可以进入设置页运行"运行检测"。

## 常见问题

`invalid_token`：

```text
Android App 使用 Authorization: Bearer <session_token>。
iPhone 快捷指令使用完整 UploadLink URL。
不要用 /api/health 验证 Token。
```

`legacy_auth_removed`：

```text
说明请求使用了旧版 APP_TOKEN、UPLOAD_TOKEN 或旧版 /api/upload-screenshot。
Android：重新获取绑定码重新绑定。
iPhone：更新快捷指令为完整 UploadLink URL。
```

`502` 或 `Bad Gateway`：

```text
确认 Windows 后端正在运行。
确认 Tunnel service 指向 http://127.0.0.1:8000。
确认后端没有被防火墙或杀毒软件拦截本地回环访问。
```

公网健康检查通，但 App 绑定失败：

```text
检查绑定码是否正确（8 位数字）。
确认绑定码未过期（默认 15 分钟）。
确认绑定码未被使用过（一次性）。
```

上传失败：

```text
确认快捷指令 URL 是完整的 UploadLink，包含 /u/<upload_key>。
确认快捷指令请求体是 文件，不是 表单。
确认已添加 User-Agent: TicketBox/1.0 iOS-Shortcut。
确认图片小于 10MB。
优先把 HEIC 转成 JPEG 或 PNG。
```

离开家里 Wi-Fi 后显示网络中断：

```text
确认 App 或快捷指令使用 https://api.zen70.cn。
确认 Windows 没有睡眠，cloudflared 和 FastAPI 都在运行。
在手机 Safari 打开 https://api.zen70.cn/api/health，应看到 {"status":"ok"}。
在 Windows 运行 scripts\check_cloudflare_endpoint.ps1。
```

查看后端和 Tunnel 当前状态、最近访问日志：

```powershell
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\check_service_status.ps1 `
  -ServerUrl https://api.zen70.cn
```

出门前建议运行一键保障检查。它会尝试启动 FastAPI 后端、启动已安装的 cloudflared 服务或计划任务，并检查公网 health：

```powershell
cd E:\projects\xiaopiaojia
powershell -ExecutionPolicy Bypass -File scripts\ensure_ticketbox_runtime.ps1 `
  -ServerUrl https://api.zen70.cn
```

如果这条命令通过，手机离开家里 Wi-Fi 后仍然可以通过 `https://api.zen70.cn` 访问。前提是 Windows 主机没有睡眠、断网或关机。

后端启动脚本默认关闭 Uvicorn access log，避免 UploadLink URL 中的 `upload_key` 被写入日志。排查上传时以脚本输出、pending 列表或数据库状态为准，不要为了看 `/u/<upload_key>` 路径临时打开访问日志。

## 官方资料

- Cloudflare Tunnel 本地应用发布：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/install-and-setup/tunnel-guide/local/
- Cloudflare Tunnel 概览：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
