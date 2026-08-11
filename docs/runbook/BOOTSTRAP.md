# Owner Bootstrap 与 Windows 首装配对

正式 Windows 分发与源码/legacy 初始化是两份不同合同，不能互相借权威：

- Inno 正式安装器只调用 `POST /api/bootstrap/installation-owner`，得到一个 8 位短期 pairing code；
- `scripts/bootstrap_owner.ps1` 与 `POST /api/bootstrap/owner` 只供源码开发、测试或明确的 legacy 人工流程，不是正式安装器路径。

> 安全基线：两个 HTTP bootstrap endpoint 都**默认禁用**，不能依赖 loopback 判断。Cloudflare Tunnel 会把公网请求转发到本机 loopback，因此 loopback 不等于真实本机用户。只有 `ENABLE_HTTP_BOOTSTRAP=true` 且 `HTTP_BOOTSTRAP_SECRET` 至少 32 字节时才开放；默认调用得到 `404 bootstrap_disabled`。

## 正式 Windows 安装器（面向用户）

安装器以受保护、短命的 bootstrap secret 调用：

```http
POST /api/bootstrap/installation-owner
Content-Type: application/json
X-Bootstrap-Secret: <安装事务短命 secret>
```

```json
{
  "operation_id": "<安装事务 ID，失败重试保持不变>",
  "installation_id": "<持久安装 ID>",
  "account_name": "我",
  "ledger_name": "我的小票夹",
  "device_name": "Windows 后端"
}
```

返回只包含 installation claim 投影与 pairing child：

```json
{
  "contract": "ticketbox-installation-owner-pairing-v1",
  "operation_id": "<原 operation_id>",
  "installation_id": "<原 installation_id>",
  "account_name": "我",
  "ledger_id": "owner",
  "ledger_name": "我的小票夹",
  "device_name": "Windows 后端",
  "pairing_code": "73829401",
  "pairing_expires_at": "2026-08-09T12:00:00Z",
  "pairing_derivation_index": 0,
  "claim_generation": 1
}
```

这里没有 `admin_token`、`upload_key` 或用户长期 bearer。安装器只在受保护的单文件 handoff 中短暂保存 pairing-only 结果并在完成页显示；Desktop Manager 由原登录用户启动，消费该码后由普通用户进程把桌面 session 写入自己的 Windows Credential Manager。

同一 `operation_id` + `installation_id` + 请求 fingerprint + secret 重试是幂等重放；pairing child 过期时在同一数据库事务中撤销旧 child、创建下一 generation，installation operation 不变。任一绑定不符都拒绝，失败事务不会只消费 secret 或留下半个 owner。系统中已有 foreign installation claim 或长期 token 时返回 `409 bootstrap_already_initialized`。

旧 `owner-bootstrap.txt`、`owner-handoff-pending` 和旧 ADR/交接记录只是审计对象。正式安装器不读取其内容、不迁移、不删除、不展示，也不允许它们阻断当前协议；需要清理旧敏感材料时必须走另一个版本化退役流程并保留脱敏回执。

## 源码/legacy 本地脚本（开发兼容）

```powershell
cd E:\projects\xiaopiaojia\backend
powershell -ExecutionPolicy Bypass -File scripts\bootstrap_owner.ps1
```

本地脚本直接调用 Python 服务层，不走 HTTP，因此不受 `ENABLE_HTTP_BOOTSTRAP` 开关影响。它会产生长期凭据文件，不属于 Inno 正式分发流程。

输出文件：

```text
backend\bootstrap\owner-bootstrap.txt
backend\bootstrap\owner-pairing.json
```

这些文件包含只显示一次的 admin token、iOS upload key 和 Android pairing code，已被 `.gitignore` 覆盖，不要提交、截图或转发给无关人员。

## Legacy HTTP API（受限开发场景）

`POST /api/bootstrap/owner` 会返回长期 admin/upload 凭据，只在确实需要通过 HTTP 自动化或烟测时才启用；正式 Windows 安装器禁止调用。启用步骤：

1. 在后端运行环境（不是 Tunnel 暴露的环境）设置环境变量：

   ```dotenv
   ENABLE_HTTP_BOOTSTRAP=true
   HTTP_BOOTSTRAP_SECRET=<一次性随机串，至少 32 字符>
   ```

   - `ENABLE_HTTP_BOOTSTRAP` 默认为 `false`。即使设为 `true`，若 `HTTP_BOOTSTRAP_SECRET` 为空仍按禁用处理。
   - 不要把 secret 写入日志、Git 历史、聊天记录或截图；只在受信通道里传递一次。

2. 调用接口必须携带 `X-Bootstrap-Secret`：

   ```http
   POST /api/bootstrap/owner
   Content-Type: application/json
   X-Bootstrap-Secret: <配置的 secret>
   ```

   ```json
   {
     "account_name": "我",
     "ledger_name": "我的小票夹",
     "device_name": "Windows 后端",
     "default_timezone": "Asia/Shanghai"
   }
   ```

3. 初始化成功后该 secret 立刻进入“已消费”集合，再次使用会返回 `401 invalid_bootstrap_secret`。务必从环境变量中删除该 secret，并确保该值不再存在于运行配置里。

返回包含：

- owner account name
- default ledger
- admin token
- iOS upload URL path `/u/{upload_key}`
- Android pairing code
- pairing code expiry

错误响应：

| 场景 | 状态码 | error |
| --- | --- | --- |
| `ENABLE_HTTP_BOOTSTRAP` 未开启或 secret 未配置 | 404 | `bootstrap_disabled` |
| 缺少 `X-Bootstrap-Secret` 请求头 | 401 | `bootstrap_secret_required` |
| secret 值不匹配或已被使用 | 401 | `invalid_bootstrap_secret` |
| 已存在活动 `auth_tokens` | 409 | `bootstrap_already_initialized` |

> Cloudflare Tunnel 防护：默认禁用即可拦截一切 Tunnel 入口的公网请求。如果确实需要通过 HTTP 远程初始化，先在 Tunnel 入口或反向代理处屏蔽 `/api/bootstrap/*`，再短暂开启 `ENABLE_HTTP_BOOTSTRAP`，并在初始化完成后立刻清空 secret。

## 生成新的 Android 绑定码

```http
POST /api/bootstrap/pairing-codes
Authorization: Bearer <admin_token 或 owner session_token>
Content-Type: application/json
```

```json
{
  "ttl_minutes": 15,
  "device_name_hint": "Android"
}
```

返回：

```json
{
  "pairing_code": "738294",
  "ledger_name": "我的小票夹",
  "expires_at": "2026-05-09T12:00:00Z"
}
```

绑定码只显示一次，只保存 hash，只能使用一次。后端在消费绑定码时使用原子条件更新标记 `used_at`，并对短时间内反复失败的绑定尝试做限流；失败过多时仍返回 `invalid_pairing_code`，但 HTTP 状态为 429。
