# 0045 CSRF 签名密钥：从公开占位常量改为 per-install 持久化密钥

- Status: accepted
- Date: 2026-06-07
- Decision makers: 项目维护者
- 说明: 安全边界改动（CSRF HMAC 密钥来源）。承重事实主张经团队三路代码侦察核实（见 Confirmation）。

## Context and Problem Statement

`/web`·`/owner` 的 CSRF token = `HMAC-SHA256(key, per-session-seed)`。`key` 取自
`middleware/csrf.py:_csrf_secret()` 的 `admin_token or http_bootstrap_secret or app_token`。
但 `admin_token` 的默认值是**非空字面量** `"replace-with-random-admin-token"`（`config.py`），
是个 truthy 值——`or` 链在第 1 项就短路。

标准 v0.3 部署里运维被明确告知**不要**设 `ADMIN_TOKEN`/`APP_TOKEN`（凭证走 DB，不走 env），
于是 CSRF HMAC 密钥 = **仓库里人人可读的公开常量**，每个 install 都一样。

今天**不可利用**（防御纵深，团队侦察确认）：① 同源门（Origin/Referer/Sec-Fetch-Site，fail-closed）
在 token 校验前挡跨站；② seed 是 per-session 256-bit 的 **HttpOnly** cookie，攻击者拿到公开 key
也没 seed。但「安全只剩 seed 这一道」——seed 一旦被 XSS 漏出或同源门被放宽，公开 key 立即可伪造。
这是 latent 风险 + 「发布在仓库里的密钥」本身就该堵。

## Decision Drivers

§0 #2 安全边界清晰；不得把公开常量当签名密钥；**线上 home server 重启=部署 HEAD，改动不得 brick**；
无现成可派生的真 secret（见下）；改动可回滚。

## Considered Options

- **密钥来源**：
  - A **app_meta 持久化随机 key**（选）：首启 `csrf_key_service.get_or_create_csrf_signing_key` 在
    `app_meta` get-or-create 一个 `secrets.token_urlsafe(32)`，进程内缓存；显式设了**真**
    `ADMIN_TOKEN`/`HTTP_BOOTSTRAP_SECRET`/`APP_TOKEN`（非占位符）仍优先（向后兼容）。
  - B 强制真 env secret + 缺则拒启动（否）：代码更简，但运维必须在下次重启前在线上设好，
    否则 home server **brick**——与「不得 brick」驱动冲突。
  - C 维持现状（否）：公开常量当密钥。
- **为何只能 A**：团队侦察确认**没有现成的真 secret 可派生**——admin/app_token 是占位常量、
  http_bootstrap_secret 一次性消费/默认空、DB admin token 只存 SHA-256 hash 不可逆、无 app-secret 表、
  无 first-boot 随机值。故必须**生成并持久化**，`app_meta`（已有 KV 表、已在 `init_db` 建、已被启动
  gate 读）是自然落点。

## Decision Outcome

Chosen：**A**。

- `_csrf_secret()`：真 env secret（非 `PLACEHOLDER_SECRETS`）优先 → 否则用启动时 stash 的 per-install key；
  占位符常量一律拒。`PLACEHOLDER_SECRETS` 在 `config.py` 命名（单一真相源，env 默认值复用之）。
- 启动（lifespan，`init_db` 后、同 session）：`set_persisted_csrf_key(get_or_create_csrf_signing_key(db))`
  + `assert_csrf_signing_key_available()`（**缺则拒启动**——但健康 DB 首启自动生成→永远自满足，只在真 DB
  故障时 fail loud）。中间件不开 per-request DB 会话（key 在启动时 stash 进模块全局）。
- 一次性轮换：首次部署后重启 key 从占位常量→随机 → 已打开的 /web 页面**至多一次提交 403，刷新即重发有效
  token**；**不掉登录、不重新配对**（session cookie 与 CSRF key 无关）。

## Consequences

Good：CSRF 密钥 per-install 唯一、不再是公开常量；无运维步骤、不 brick（首启自provision）；向后兼容显式
真 env secret。Bad/成本：`app_meta` 多一行 `csrf_signing_key`；csrf.py 多一个启动期 stash 的进程全局；
一次性刷新成本（自愈）。**同根残留（本轮不动）**：budget-advisor audit HMAC（`_audit.py`）复用同一
`admin_token→http_bootstrap_secret→app_token` 链，同样退化——可日后改派生自同一 per-install key 源。
回收：改动可回退（删 key 来源回到 env 链）；要引入专用 `CSRF_SIGNING_SECRET` env 另评。

## Confirmation

`backend/tests/test_csrf_signing_key.py`：get_or_create 幂等 + 非占位 + 持久化；`_csrf_secret` 真 env 优先；
占位符被拒→回退持久化 key。`test_public_web_security_layers.py`：占位 env + 持久化 key → /web 仍渲染 token
（不 500）；真无 key（env 空 + 持久化清空）→ fail-closed 500。`csrf-dual-mode` release_audit lane 保持绿。

## More Information

- 承重事实（已回代码核实）：占位短路 `csrf.py:_csrf_secret`、`config.py` 默认值；同源门 + HttpOnly per-session
  seed 双控；无现成可派生真 secret（admin token hash-only `models/identity.py`、bootstrap secret 一次性
  `routes/bootstrap.py`）；`app_meta` KV + 启动 gate 先例 `services/app_meta_service.py`。
- 关联：[[0031]] app_meta；ENGINEERING_RULES §5 鉴权/安全、§14 三端 token。
