# v0.3 Bootstrap Owner

首次启动或迁移到 v0.3 后，先初始化 owner 身份。

> 安全基线：HTTP `/api/bootstrap/owner` **默认禁用**，不能再依赖 loopback 判断。Cloudflare Tunnel 会把所有公网请求转发到本机 loopback，因此 loopback 不等于真实本机用户。**默认运行下，公网（含 Tunnel）调用 `/api/bootstrap/owner` 会得到 `404 bootstrap_disabled`。**

## 本地脚本（推荐）

```powershell
cd E:\projects\xiaopiaojia\backend
powershell -ExecutionPolicy Bypass -File scripts\bootstrap_owner.ps1
```

本地脚本直接调用 Python 服务层，不走 HTTP，因此不受 `ENABLE_HTTP_BOOTSTRAP` 开关影响。

输出文件：

```text
backend\bootstrap\owner-bootstrap.txt
backend\bootstrap\owner-pairing.json
```

这些文件包含只显示一次的 admin token、iOS upload key 和 Android pairing code，已被 `.gitignore` 覆盖，不要提交、截图或转发给无关人员。

## HTTP API（受限场景）

仅在确实需要通过 HTTP 自动化或烟测时才启用。启用步骤：

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
