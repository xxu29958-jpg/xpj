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

允许公网（allowlist）：

| 路径前缀 | 用途 | 鉴权 |
|---|---|---|
| `/api/health` | Liveness 探测，只返回 `{"status":"ok"}` | 无 |
| `/api/auth/check` | Android session token 校验 | Bearer token |
| `/api/auth/pair` | Android 首次绑定（pairing code → session token）| 8 位 code，一次性 + 短 TTL |
| `/api/expenses/*` `/api/reports/*` `/api/goals/*` `/api/dashboard/*` `/api/budgets/*` `/api/recurring/*` `/api/merchants/*` `/api/rules/*` `/api/duplicates/*` `/api/imports/*` `/api/stats/*` `/api/me/*` `/api/exchange-rates/*` `/api/settings/*` `/api/ledgers/*` `/api/invitations/*` | Android / Web 账本主面 | Bearer token + viewer/member/owner 角色 |
| `/u/{upload_key}` | iPhone UploadLink | 一次性 upload_key（URL-as-credential，必须 HTTPS）|
| `/web/auth/login` | 浏览器登录页和绑定码提交 | GET 无 cookie 返回 200；POST 需 CSRF；成功后 `303` 并设置 `__Host-session` |
| `/web/auth/logout` | 浏览器退出 | POST 需 CSRF；只撤销 web token 并清除 cookie |
| `/web/auth/whoami` | 浏览器 session 自检 | 有效 `__Host-session` 返回 200；无效返回 `401 invalid_token` |
| `/web/*` | 浏览器版账本 | Cloudflare Access JWT（生产建议） + `__Host-session` HttpOnly Secure cookie；`auth_tokens.expires_at` 固定 8h server-side TTL；无 cookie 返回 `303 Location: /web/auth/login?next=...` |
| `/static/web/*` | `/web` 桌面账本 CSS/JS/font/vendor | 只放无用户数据的静态前端资产 |
| `/static/shared/*` | `/web` 与 `/owner` 共享设计 token / confirm-modal 资源 | 只放无用户数据的共享静态资产；公网仅供 `/web` 渲染 |

拒绝公网（denylist / Tunnel 不要建路由）：

| 路径前缀 | 理由 |
|---|---|
| `/owner/*` | Owner Console 永远 loopback only；backend 自带 `require_owner_console_local`，Tunnel 路由层再 deny 一遍是 defense in depth |
| `/api/admin/*` | 默认 `ALLOW_PUBLIC_ADMIN_API=false`，且 backend 挂 `require_admin_network_boundary`；Tunnel 不要建路由 |
| `/api/bootstrap/*` | `enable_http_bootstrap=false` 默认关；`/api/bootstrap/pairing-codes` 已挂 `require_admin_network_boundary`；Tunnel 不要建路由 |
| `/api/maintenance/*` | 同 admin |
| `/api/status/private` | 私有运行状态（版本、DB、上传目录等），需要 Bearer token；默认不走公网 allowlist |
| `/docs` `/redoc` `/openapi.json` | `ENABLE_API_DOCS=false` 默认关 |
| `/static/owner/*` | Owner Console 静态资源跟随 `/owner` loopback only，不走公网 |
| `/static/uploads/*` | 上传图片目录永不公开；即使路径猜中也必须 404 |
| `/static/*` 其它子树 | 默认不暴露；新增公网静态子树必须先有 ADR 和 allowlist |
| 实际 uploads 目录 | 永不挂载为静态；图片只通过 `/api/expenses/{id}/image` 鉴权读 |

Tunnel 公网 hostname 配置时只给上面 allowlist 的路径建 Public Hostname 条目，每条 Service 都指 `http://127.0.0.1:8000` + path matcher。或者用单一 hostname + Cloudflare Rules / Workers 在边缘做路径过滤。

## WAF rate limit 规则建议

Cloudflare Free Plan 2022 起已经包含 unmetered rate limiting（不算钱），可以直接配。下面是按攻击面权衡的起步规则：

| 规则名 | 匹配 | 限速 | 动作 | 理由 |
|---|---|---|---|---|
| upload-link-anti-scan | `path ~ "^/u/"` | 10 req/min/IP | challenge | UploadLink 凭证在 URL 里，必须挡爆破扫描 |
| pair-anti-brute | `path eq "/api/auth/pair"` | 5 req/min/IP | block 10 min | 8 位 pairing code 防爆破；正常用户成功一次就够 |
| auth-check-loose | `path eq "/api/auth/check"` | 60 req/min/IP | log only | App 启动时高频；不挡，但留可观测窗口 |
| api-default | `path ~ "^/api/"` | 100 req/min/token (用 `Authorization` header 当 characteristic) | challenge | 正常 client 远低于；超过基本是凭证泄露后扫表 |
| size-cap | `cf.threats.request.content_length gt 10485760` | n/a | block | matches backend `MAX_UPLOAD_SIZE_MB=10` |

配置入口：Cloudflare dashboard → Security → WAF → Rate limiting rules。

注意 `characteristic` 选择：
- `/u/*` 用 client IP（无 token）
- `/api/auth/pair` 用 client IP（pair 之前没 token）
- 其它 `/api/*` 用 `Authorization` header（防止单 token 被多 IP 共享后绕单 IP 限）

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

2026 推荐**远程管理 tunnel**（config 放 Cloudflare dashboard，本机 cloudflared 只需要 token），不再用本机 `config.yml`。优点：
- 多 replica HA 共享同一 tunnel ID
- 改 ingress 不用重启本机进程
- token 不掉地（dashboard 一次性 reveal）

如果坚持要本机 config，最小 starter（**仅参考，实际部署用 dashboard**）：

```yaml
# 仅本机调试参考，生产用 dashboard remote-managed config
tunnel: <tunnel-uuid>
credentials-file: C:\Users\<you>\.cloudflared\<tunnel-uuid>.json

ingress:
  # allowlist 优先匹配
  - hostname: api.your-domain.com
    path: ^/(web(?:/|$)|static/(?:web|shared)(?:/|$)|u/|api/(?:health$|auth/(?:check|pair)$|expenses(?:/|$)|reports(?:/|$)|goals(?:/|$)|dashboard(?:/|$)|budgets(?:/|$)|recurring(?:/|$)|merchants(?:/|$)|rules(?:/|$)|duplicates(?:/|$)|imports(?:/|$)|stats(?:/|$)|me(?:/|$)|exchange-rates(?:/|$)|settings(?:/|$)|ledgers(?:/|$)|invitations(?:/|$)))
    service: http://127.0.0.1:8000
  # catch-all return 404，绝对不要让其它路径漏到 backend
  - service: http_status:404
```

## 官方资料

- Cloudflare Tunnel 本地应用发布：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/install-and-setup/tunnel-guide/local/
- Cloudflare Tunnel 概览：https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/
- Cloudflare Access self-hosted public app：https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/self-hosted-public-app/
- Cloudflare Access JWT validation：https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/
- Cloudflare unmetered rate limiting：https://blog.cloudflare.com/unmetered-ratelimiting/
- Cloudflare WAF rate limit best practices：https://developers.cloudflare.com/waf/rate-limiting-rules/best-practices/
