# Cloudflare Tunnel 配置说明

正式 Windows 安装的公网连接从**小票夹管理器**设置。Backend 保持 `http://127.0.0.1:8000`，
公网使用专属 HTTPS 地址。无需开放路由器端口或保留终端；不能把 Backend 改为 `0.0.0.0`，
也不能把 `uploads/` 直接公开。以下说明是操作与边界契约，发行资格仍须绑定实际安装包和测试结果。

## 首次设置

1. 在 Cloudflare 账户内为此电脑建立专用 remotely-managed Tunnel 和专用 hostname。
   按下文“公网路由分层”应用完整 ingress，保留末尾 404；不要执行控制台提供的全局 service install 命令。
2. 在小票夹设置中保存该 HTTPS 地址。保存地址使用当前合法 Owner 身份；本机安装另由 Windows 授权。
3. 回到管理器点击“设置公网连接”，完成一次 Windows 授权，在随后打开的遮蔽输入框粘贴 Tunnel Token。
   不把 Token 发到聊天、普通网页、脚本参数或环境变量。取消输入不会替换既有凭据或启动候选连接。
4. 主机操作结束后自动检查公网。以管理器当前结果和覆盖范围为准，再从原有入口连接 Android、Web 或 iPhone。
   “本机完成，公网待验证”允许继续使用本地账本，不等于公网已可用。

连接完成后关闭管理器不影响后台运行；日常无需重新粘贴 Token。
“暂停公网”只关闭本机受管连接并跨重启保持；“开启公网”恢复这一连接。
“重新连接”沿用既有配置，执行一次有限操作；不会重新安装、轮换凭据或清空手机任务。
替换凭据和移除位于连接详情。暂停期间替换凭据仍保持暂停。
移除只处理本机拥有的服务与凭据；远端撤销仍由 Cloudflare 账户持有人完成。

## 失败后继续

管理器重开后读取同一操作的记录。只有原请求、当前安装身份与可安全重复的步骤相符，才提供“继续上次操作”。
地址已变化或原配置不能继续时，提供关闭该未完成配置的明确下一步。
结果无法确认时先刷新并查看诊断；不会自动创建另一个操作或反复重装。

## 已有外部连接或旧电脑

外部服务、登录任务与手工进程仍归原工具管理，小票夹不会从它们的命令行读取 Token，
也不会按名称起停、升级或删除。默认使用新的专用 Tunnel；共享连接不得整体停止。
沿用已有 hostname 时，先在原管理工具或 Cloudflare 中确认旧目标已退出该地址的转发，
再启用新目标并核对当前安装身份。旧电脑和新电脑同时连接同一 Tunnel，可能分流到不同账本；
一次成功请求不证明交接完成。不能确认远端退出时，应停在待交接状态，或改用新的专用地址。

旧 `ensure_ticketbox_runtime.ps1` 与 `install_windows_tasks.ps1` 已移除连接器控制：
不再扫描或启动 cloudflared 服务，不推断运行参数，不创建 Tunnel 登录任务。
源码运维脚本遇到正式安装或相关服务会在任何动作前拒绝，并指向管理器。
保留的源码后端工具仅供未安装产品的外部手工环境；见 [Windows 运行说明](WINDOWS_SERVICE_RUNBOOK.md)。

## 验收与支持

日常检查在管理器完成，详情可导出允许字段的诊断摘要。工程验收仍可使用
`check_cloudflare_endpoint.ps1`、`check_public_boundary.ps1` 和 `real_device_preflight.ps1`，
必须针对实际目标与有效产品身份执行；脚本结果不替代普通用户旅程或独立网络客户端证据。
这些只读检查不负责启动连接器。真实上传探针会产生待确认记录，应使用隔离测试账本。

### 固定版本的维护责任

本仓库所有者 `xxu29958-jpg` 是本组件的唯一发行责任人，负责版本跟踪、安全修复评估、
兼容验证、发布说明与旧版本退役。责任交接须在发行说明中明确新的负责人；不能将更新责任
转给普通用户手工覆盖程序目录。Cloudflare 账户持有人仍负责远端账号、DNS 与 Token。

当前候选绑定 `2026.10.3`（上游发布于 2026-10-21），版本、官方来源、签名、摘要及许可证
均由 `backend/packaging/cloudflared-profile.json` 固定。Cloudflare 的当前规则为一年支持窗口，
Windows 也不会自动更新；每次发行及每月维护复核时重新检查
[官方支持说明](https://developers.cloudflare.com/tunnel/downloads/)与
[上游发布](https://github.com/cloudflare/cloudflared/releases/tag/2026.10.3)。
上游缩短支持或出现安全修复时，按更早的要求处理，不能仅凭固定日期继续声明可支持。

本候选最晚在 **2027-07-21 前**由同一发行责任人完成替代版本的资格与发布，预留至少三个月
维护余量。优先沿已取得资格的完整发行升级路径；若该路径届时仍未取得资格，则只交付最窄的
连接器版本维护切片：验证受信候选、精确停启、秘密与暂停意图保留、中断后的明确继续方式，
以及旧版本恢复边界，并在管理器提供用户可达入口。该维护切片目前尚未取得资格，不能宣称
已经支持独立热更新或完整 U1，也不能直接覆盖 immutable app_dir。

首版发布必须同时确认负责人、当前支持窗口和上述维护期限。未能按期取得替代资格、上游提前
停止支持或发现无法缓解的安全风险时，发行责任人停止发布受影响候选并通知已安装用户暂停公网；
本地账本与既有数据继续保留。正式 EXE 只接受小票夹核准发行路径，不能交给 cloudflared
自身、包管理器或另一套脚本并行更新。

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

快捷指令沿用文件请求正文，必要时转换为 JPEG 或 PNG。历史使用说明不替代本次目标 iOS 真机资格；新模板的可用声明单独以真机结果为准。

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

离开家里 Wi-Fi 后显示网络中断：在小票夹管理器查看“公网连接”。
先确认电脑在线且未睡眠，再根据当前原因处理；可运行完整检查并导出诊断。
健康端点返回 200、一个 cloudflared 进程存在或 Edge 已连接，都不能单独证明账本身份与业务路径正确。
普通网络中断不需要重新配对手机、清理待上传任务或更换连接凭据。

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
