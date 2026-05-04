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
powershell -ExecutionPolicy Bypass -File scripts\check_cloudflare_endpoint.ps1 `
  -ServerUrl https://api.zen70.cn
```

脚本会：

- 检查 `/api/health`。
- 检查 `/api/auth/check`。
- 用内置 1x1 PNG 测试 `/api/upload-screenshot`。
- 从 `backend\.env` 读取 `APP_TOKEN` 和 `UPLOAD_TOKEN`，但不会打印 Token。

当前 Windows 联调推荐同时启用两个登录自启任务：

```powershell
Get-ScheduledTask -TaskName TicketboxBackend,TicketboxCloudflareTunnel
```

其中：

- `TicketboxBackend` 启动本机 FastAPI：`127.0.0.1:8000`。
- `TicketboxCloudflareTunnel` 启动 Cloudflare Tunnel connector。

只检查健康和 App Token，不上传测试图：

```powershell
powershell -ExecutionPolicy Bypass -File scripts\check_cloudflare_endpoint.ps1 `
  -ServerUrl https://api.你的域名.com `
  -SkipUpload
```

## iPhone 快捷指令 URL

快捷指令上传地址：

```text
https://api.你的域名.com/api/upload-screenshot
```

请求头：

```text
Upload-Token: 你的UPLOAD_TOKEN
```

请求体：

```text
multipart/form-data
字段名：file
```

建议在快捷指令里先转换为 JPEG 或 PNG。

## Android 绑定地址

Android App 首次绑定服务器地址：

```text
https://api.你的域名.com
```

Token 使用：

```text
APP_TOKEN
```

绑定后进入设置页运行“联调自检”。

## 常见问题

`invalid_token`：

```text
iPhone 上传只用 Upload-Token。
Android App 只用 Authorization: Bearer APP_TOKEN。
不要用 /api/health 验证 Token。
```

`502` 或 `Bad Gateway`：

```text
确认 Windows 后端正在运行。
确认 Tunnel service 指向 http://127.0.0.1:8000。
确认后端没有被防火墙或杀毒软件拦截本地回环访问。
```

公网健康检查通，但 App Token 失败：

```text
检查 backend\.env 中的 APP_TOKEN。
确认 Android 输入的是 APP_TOKEN，不是 UPLOAD_TOKEN。
```

上传失败：

```text
确认快捷指令字段名是 file。
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
powershell -ExecutionPolicy Bypass -File scripts\show_server_status.ps1
```

如果手机请求真的打到了后端，应该能在 `backend\logs\ticketbox-backend-*.out.log` 里看到对应接口和状态码。若这里没有任何新请求，问题在手机网络、域名、Cloudflare Tunnel 或快捷指令请求发起阶段，后端日志不会凭空出现。

## 官方资料

- Cloudflare Tunnel 本地应用发布：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/install-and-setup/tunnel-guide/local/
- Cloudflare Tunnel 概览：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
