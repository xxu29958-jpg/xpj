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
- 在公网边界脚本中检查 `/web/auth/login` 可达、`/web/*` 无 cookie 返回 `303`，且 `Location` 指向 `/web/auth/login?...`。

> **注意**：v0.3 以后脚本不再从 `backend\.env` 读取旧 `APP_TOKEN`/`UPLOAD_TOKEN`，也不接受命令行传 token。请通过 `TICKETBOX_SESSION_TOKEN` / `TICKETBOX_UPLOAD_LINK` 环境变量传入当前有效凭证，避免 token 进入 PowerShell 历史。`UploadLink` 可以是完整 URL，也可以是 `/u/<upload_key>?tz=...` 路径。

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
$env:TICKETBOX_SESSION_TOKEN="<session_token>"
powershell -ExecutionPolicy Bypass -File scripts\check_cloudflare_endpoint.ps1 `
  -ServerUrl https://api.你的域名.com `
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

## 公网路由分层（必读）

Cloudflare Tunnel 配置 ingress 时，下面两类路径互不重叠。**不要**把整个 `/` 直接转发给 `127.0.0.1:8000`——必须按路径白名单/黑名单切。

`/web` 的公网形态不是裸公开，而是四层叠加：

1. Cloudflare Tunnel 只转发 allowlist 路径，catch-all 返回 404。
2. Cloudflare Access 保护 `/web/*`、`/static/web/*`、`/static/shared/*`；生产建议后端设置 `CLOUDFLARE_ACCESS_REQUIRED=true`，并校验 `Cf-Access-Jwt-Assertion`。
3. 后端 `web_session_gate` 校验 `__Host-session` cookie，只接受 `AuthToken.scope="app"` 且 `Device.platform="web"` 的浏览器 token。
4. 账本渲染和写操作继续使用 ledger/session permission，URL 上跨账本 `ledger_id` 直接 `403 ledger_forbidden`。

`/web/auth/login` 负责浏览器绑定码登录；其它 `/web/*` 请求必须带后端签发的 `__Host-session` cookie。没有 cookie、cookie 无效或服务端固定 TTL 过期时，后端返回 `303`，`Location` 指向 `/web/auth/login?next=...`，并在无效 cookie 场景清除 cookie。有有效 cookie 时，后端按 session 绑定的账本渲染页面。服务端 Web token 写入 `auth_tokens.expires_at`，固定 8 小时有效，不做滑动刷新；到期后重新 pairing。所有 `/web` 与 `/owner` 非安全方法还必须通过同源来源头 + CSRF token 校验。

公网路径、方法和鉴权责任以 [完整路由清单](PUBLIC_ROUTE_CATALOG.md) 为准。
清单逐项覆盖当前注册路由和实际 Android 声明，包括会话刷新、App 上传、资金账户、
收入计划、任务、债务/分账、标签、还款草稿等产品入口。`/api/status/private` 继续私有。
本机身份确认 `/web/auth/local`、Desktop 币种设置、`/owner`、`/desktop`、安装证明、
管理/维护/引导 API、文档、metrics 和上传目录均不进入公网 ingress。

使用 [生成的 remote-managed ingress 配置](cloudflared-ingress.example.json)，
将每条 hostname 改为同一个专用域名，Service 的端口改为该安装的 Backend 端口。
必须保留最后的 `http_status:404`，移除同域名下其它宽泛或重叠的转发规则。
不得把整个 `/api`、自动导出的所有 OpenAPI 路由或未分类 Web 路由直接放行。
不要设置 `httpHostHeader` 为 localhost/127.0.0.1；Backend 必须看到公网 Host。

配置只约束路径；HTTP 方法、App Bearer、Web cookie、UploadLink capability、角色、
账本隔离和 CSRF 仍由 Backend 执行。可选 Access 只覆盖 `/web`、`/web/*` 和对应静态资源。
Android API、认证刷新和 `/u/{upload_key}` 不得被 Access 登录页或 WAF JavaScript challenge 拦截。

## WAF rate limit 规则

按 Cloudflare 当前账号实际可用能力配置，本文不声明套餐额度或无限免费规则。
连接码和 UploadLink 的后端限流及有效期仍生效；边缘限流不能替代这些校验。
原生 API 与 UploadLink 超限时使用客户端能识别的拒绝响应，不使用交互式 challenge。
配额应按真实同步、上传和重试流量验证，不能用一个过低的 `/api/*` 全局阈值截断正常客户端。

## Cloudflare Access 四层部署

Android / iPhone 不适合走 Access（service token 烧进 APK 不可控，参见 [Cloudflare service token 文档](https://developers.cloudflare.com/cloudflare-one/access-controls/service-credentials/service-tokens/)）。Access 只建议放在浏览器 `/web/*` 前面，作为 Web session 之外的外层身份门。

后端支持校验 Cloudflare Access application token。生产启用四层时，配置：

```env
CLOUDFLARE_ACCESS_REQUIRED=true
CLOUDFLARE_ACCESS_TEAM_DOMAIN=https://<your-team-name>.cloudflareaccess.com
CLOUDFLARE_ACCESS_AUD=<Application Audience AUD Tag>
```

Cloudflare 官方说明 Access 会把 application token 发送到 origin 的 `Cf-Access-Jwt-Assertion` header，origin 应使用 team domain 的 JWKS 和应用 AUD 校验该 JWT。后端只把这个 header 用作 Access 身份层；最终账本权限仍以本机 `__Host-session` 和 ledger permission 为准。

边界探测：

```powershell
$env:TICKETBOX_CF_ACCESS_JWT="<从受控浏览器请求中临时取出的 Cf-Access-Jwt-Assertion>"
powershell -ExecutionPolicy Bypass -File scripts\check_public_boundary.ps1 `
  -BaseUrl https://api.zen70.cn
```

不要把 Access JWT 写入命令行参数、日志或文档；只通过临时环境变量传入脚本。若 `CLOUDFLARE_ACCESS_REQUIRED=true` 但请求没有有效 Access JWT，公网 `/web/*` 和 `/static/web/*` 应返回 `403 cloudflare_access_required` 或 `403 cloudflare_access_invalid`，而不是进入后端 Web session。

## Tunnel config 形态

本专项使用专用 remotely-managed Tunnel 和专用 hostname；远端 DNS、ingress、Access/WAF
及 Token 轮换由 Cloudflare 账号持有人管理。受管本机动作不需要账号密码、Global API Key
或 `cert.pem`。Token-only connector 运行中会接收远端配置更新，本机 JSON/YAML 或历史探测
回执不能锁定远端策略。验证时检查当前实际请求结果；该结果不等同于账号级配置审计。

正式凭据采用 ACL 保护的明文 `--token-file`，不宣称“不落地”或 DPAPI 加密；输入必须在
提升权限后的原生入口完成，不能把原始 Token 放入命令行、普通浏览器、环境变量、日志或操作记录。
当前源码中受管四动作的交付资格以专项现行交接为准；手工外部 connector 不会自动变成受管实例。

重生成和检查路由材料：

```powershell
python backend/scripts/render_public_routes.py
python backend/scripts/render_public_routes.py --check
```

只编辑 `backend/scripts/public_route_catalog.py` 的审核分类，不手工改生成的清单或配置。
变更后运行 `backend/packaging/tests/test_public_route_catalog.py`，核对实际端点、方法、Android
消费者和全部私有路由，再在远端账号应用该配置并执行实际公网资格检查。

## 官方资料

- Cloudflare Tunnel 本地应用发布：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/install-and-setup/tunnel-guide/local/
- Cloudflare Tunnel 概览：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- Cloudflare Access self-hosted public app：https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/
- Cloudflare Access JWT validation：https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- Cloudflare unmetered rate limiting：https://blog.cloudflare.com/unmetered-ratelimiting/
- Cloudflare WAF rate limit best practices：https://developers.cloudflare.com/waf/rate-limiting-rules/best-practices/
