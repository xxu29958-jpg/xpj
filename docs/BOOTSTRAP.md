# v0.3 Bootstrap Owner

首次启动或迁移到 v0.3 后，先初始化 owner 身份。

## 本地脚本

```powershell
cd E:\projects\xiaopiaojia\backend
powershell -ExecutionPolicy Bypass -File scripts\bootstrap_owner.ps1
```

输出文件：

```text
backend\bootstrap\owner-bootstrap.txt
backend\bootstrap\owner-pairing.json
```

这些文件包含只显示一次的 admin token、iOS upload key 和 Android pairing code，已被 `.gitignore` 覆盖，不要提交、截图或转发给无关人员。

## API

推荐使用本地脚本。API 入口只接受后端本机请求，用于首次初始化或自动化烟测；不要把它作为公网初始化入口。

```http
POST /api/bootstrap/owner
```

示例请求：

```json
{
  "account_name": "我",
  "ledger_name": "我的小票夹",
  "device_name": "Windows 后端",
  "default_timezone": "Asia/Shanghai"
}
```

返回包含：

- owner account name
- default ledger
- admin token
- iOS upload URL path `/u/{upload_key}`
- Android pairing code
- pairing code expiry

如果已经存在活动 `auth_tokens`，接口返回 `bootstrap_already_initialized`。

如果请求不是来自本机 loopback，接口返回 `invalid_token`（403）。

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
