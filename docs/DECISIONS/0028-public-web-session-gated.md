# 0028 Public Web Session-Gated Surface

- 状态：accepted
- 日期：2026-05-23
- 上下文：v1.0 public browser access hardening
- 决策人：项目维护者

## 背景

历史规则要求 Cloudflare Tunnel 公网只暴露 `/api/*` 和 `/u/{upload_key}`，`/web` 与 `/owner` 都强制 loopback。现在家庭成员需要在外部浏览器访问既有 `/web` 桌面账本，但项目仍不引入公网账号密码系统，也不把 Owner Console 暴露到公网。

这不是单一开关。公网 `/web` 必须同时满足边缘 allowlist、Cloudflare Access（生产建议）、后端 Host/peer 双判定、服务端 web session、以及账本权限边界。

## 决策

允许 Cloudflare Tunnel 将以下路径转发到本机后端：

- `/web` 与 `/web/*`
- `/static/web/*`
- `/static/shared/*`

`/web` 公网访问必须由 Cloudflare Access（生产建议）和后端 `web_session_gate` 共同保护：

- loopback peer + loopback Host 仍保留本机免 cookie 体验。
- Cloudflare connector peer 是本机，但 Host 是公网域名时按公网请求处理。
- 生产部署建议设置 `CLOUDFLARE_ACCESS_REQUIRED=true`；后端必须校验 `Cf-Access-Jwt-Assertion` 的签名、issuer 和 AUD，不能只相信边缘已经拦截。
- 公网 `/web/auth/login` 可达，用 owner 生成的 8 位 pairing code 登录。
- 登录复用 `pair_device(platform="web")`，签发 `AuthToken.scope="app"`、`Device.platform="web"`，并写入 `auth_tokens.expires_at = issued_at + 8h`。
- 公网 `/api/auth/pair` 是无 app/admin token 的绑定入口，只接受 owner 通过 `/api/bootstrap/pairing-codes` 在 loopback/admin 边界内生成的 pairing code；它只能作为 DB-backed `remote_id` throttle 的受限 bootstrap 入口，不能把 `X-Forwarded-For` / `CF-Connecting-IP` 当作授权信号。
- 其它公网 `/web/*` 必须带 `__Host-session` HttpOnly Secure SameSite=Strict cookie。
- web session 校验必须同时检查 token scope 和 device platform，不能接受 Android/app token。
- 服务端 Web token 按 `auth_tokens.expires_at` 固定 8 小时有效，不做滑动刷新；到期撤销 token 并重新 pairing。
- cookie 绑定 ledger；URL `?ledger_id=` 与 session ledger 不一致时返回 `ledger_forbidden`。
- `/web` 与 `/owner` 的非安全方法必须通过同源来源头 + CSRF token，SameSite cookie 只作为附加防线。
- 为校验 Cloudflare Access JWT，引入运行时依赖 `PyJWT[crypto]`（精确 pin，按 PyPI 当前稳定版维护）。

Cloudflare 边缘仍必须拒绝：

- `/owner/*`
- `/api/admin/*`
- `/api/bootstrap/*`
- `/api/maintenance/*`
- `/docs`、`/redoc`、`/openapi.json`
- `/static/owner/*`
- `/static/uploads/*`
- 实际 uploads 目录

公网探测允许 forbidden 路径被 Cloudflare catch-all 直接返回 404，也允许请求到达后端后返回对应 JSON 错误。两者都表示边界关闭。

## 后果

`docs/rules/ENGINEERING_RULES.md` 的公网边界从“`/web` 永远 loopback”更新为“`/web` 公网 session-gated，`/owner` 永远 loopback”。后续修改 `/web` 静态资源路径、cookie TTL、登录方式、或 Cloudflare allowlist 都必须同步更新 runbook、边界探测脚本和相关测试。

不做：

- 不开放 `/owner`。
- 不新增账号密码系统。
- 不让 Cloudflare Access 成为唯一身份边界；Access 只是四层中的外层身份门，后端仍必须验证 `Cf-Access-Jwt-Assertion`，并继续校验本机 Web session 和账本权限。
- 不公开上传图片或 Owner Console 静态资源。
