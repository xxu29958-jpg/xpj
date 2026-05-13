# 小票夹 API 文档

基础地址：

```text
http://127.0.0.1:8000
```

公网通过 Cloudflare Tunnel 映射到自己的域名，例如：

```text
https://api.我的域名.com
```

## 统一规则

时间：

- 数据库存 UTC。
- API 返回 ISO 8601 字符串，例如 `2026-05-03T04:20:00Z`。
- 统计优先按 `expense_time`，为空时按 `confirmed_at`。
- `timezone` / `X-Timezone` 使用 IANA 时区名。未传 `timezone` 时使用服务端 `OCR_DEFAULT_TIMEZONE`；传入无效时区名时，当前查询边界按 UTC 降级，上传 OCR 草稿解析按服务端默认时区降级。

金额：

- 全链路使用 `amount_cents`。
- 单位为分。
- 不使用 float/double 保存金额。

标识：

- 后端自增 `id` 仍用于当前 API 路径，例如 `/api/expenses/{id}`。
- `public_id` 是账单公共 UUID，用于导出、跨端同步、排查问题和未来多端合并。
- Android Room 同时保存 `serverId` 和 `publicId`，二者都必须唯一。
- 普通 UI 不直接展示 UUID；需要给用户看时使用"账单编号"等生活化文案。

错误：

```json
{
  "error": "错误代码",
  "message": "中文错误说明"
}
```

常见错误码：

```text
invalid_token
legacy_auth_removed
bootstrap_already_initialized
invalid_pairing_code
pairing_code_expired
pairing_code_used
file_too_large
unsupported_file_type
expense_not_found
amount_required
image_not_found
rule_not_found
permission_denied
server_error
invalid_request
route_not_found
method_not_allowed
```

## 认证

v0.3 使用可撤销凭证系统替代旧版静态 token。

### 设备绑定（Pairing Code → Session Token）

Android 首次绑定：

1. 用户向服务拥有者索要 6 位 Pairing Code。
2. 调用 `POST /api/auth/pair` 提交 pairing_code + device_name + platform。
3. 后端返回 `session_token`。
4. Android 保存 `session_token` 到 Keystore，后续所有请求使用：

```http
Authorization: Bearer <session_token>
X-Timezone: Asia/Shanghai
```

### iPhone 上传（UploadLink）

iPhone 快捷指令使用完整 UploadLink URL，不再需要请求头鉴权：

```text
POST https://api.我的域名.com/u/<upload_key>?tz=Asia/Shanghai
```

### 维护接口（Admin Token）

Owner 初始化时通过 `POST /api/bootstrap/owner` 获得 `admin_token`，用于维护接口：

```http
Authorization: Bearer <admin_token>
```

### 旧版 Token（已废弃）

旧版 `APP_TOKEN`、`UPLOAD_TOKEN` 和 `TENANTS_JSON` 中的 app/upload token 请求返回 `legacy_auth_removed`（401）。旧版静态 `ADMIN_TOKEN` 不再是运行时凭证；维护接口只接受数据库 `auth_tokens.scope=admin` 中保存 hash 的 admin token，旧静态 admin 值会按普通无效凭证处理。

## API 契约矩阵

| Endpoint | Method | 后端 route | Android ApiService | 请求 DTO / 参数 | 响应 DTO | 鉴权 | 测试覆盖 | 用途 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `/api/health` | GET | `backend/app/main.py` | 无 | 无 | `{"status":"ok"}` | 无 | `backend/tests/test_auth_bootstrap.py`, smoke | smoke |
| `/api/bootstrap/owner` | POST | `backend/app/routes/bootstrap.py` | 无 | `BootstrapOwnerRequest` | `BootstrapOwnerResponse` | 默认禁用；启用后需 `X-Bootstrap-Secret`（一次性） | `backend/tests/test_auth_bootstrap.py` | owner 初始化 |
| `/api/bootstrap/pairing-codes` | POST | `backend/app/routes/bootstrap.py` | 无 | `PairingCodeCreateRequest` | `PairingCodeResponse` | Admin Token | `backend/tests/test_auth_bootstrap.py` | 生成新绑定码 |
| `/api/auth/pair` | POST | `backend/app/routes/auth.py` | `pairDevice()` | `PairRequest` | `PairResponse` | 无 | `backend/tests/test_auth_bootstrap.py` | 设备绑定 |
| `/api/auth/check` | GET | `backend/app/routes/auth.py` | `checkAuth()` | header `Authorization` | `AuthCheckDto` | Session Token | `backend/tests/test_auth_bootstrap.py` | 校验 session |
| `/api/upload/check` | GET | `backend/app/routes/uploads.py` | 无 | 旧版 `Upload-Token` | 错误响应 | 旧版 Upload-Token（已废弃） | `backend/tests/test_auth_bootstrap.py`, smoke | 旧版上传检查（已废弃） |
| `/api/upload-screenshot` | POST | `backend/app/routes/uploads.py` | 无 | raw image 或 multipart | `UploadResponseDto` | 旧版 Upload-Token（已废弃） | `backend/tests/test_uploads.py`, smoke | 旧版 iPhone 入口（已废弃） |
| `/u/{upload_key}` | POST | `backend/app/routes/uploads.py` | 无 | raw image 或 multipart；query `tz` | `UploadResponseDto` | UploadLink URL | `backend/tests/test_uploads.py`, smoke | iPhone 快捷指令上传 |
| `/api/app/upload-screenshot` | POST | `backend/app/routes/uploads.py` | `uploadScreenshot(file, timezone)` | multipart `file`；header `X-Timezone` | `UploadResponseDto` | Session Token | `backend/tests/test_uploads.py`, `ApiDtoContractTest` | Android 上传 |
| `/api/expenses/pending` | GET | `backend/app/routes/expenses.py` | `pendingExpenses()` | 无 | `List<ExpenseDto>` | Session Token | `backend/tests/test_expenses.py`, smoke | gray/internal |
| `/api/expenses/confirmed` | GET | `backend/app/routes/expenses.py` | `confirmedExpenses(page,pageSize,month,category,timezone)` | query `page/page_size/month/category/timezone` | `PaginatedExpensesDto` | Session Token | `backend/tests/test_stats_filters.py`, Android domain tests | gray/internal |
| `/api/expenses/categories` | GET | `backend/app/routes/expenses.py` | `categories()` | 无 | `CategoriesDto` | Session Token | `backend/tests/test_stats_filters.py` | gray/internal |
| `/api/expenses/months` | GET | `backend/app/routes/expenses.py` | `months(timezone)` | query `timezone` | `MonthsDto` | Session Token | `backend/tests/test_stats_filters.py` | gray/internal |
| `/api/expenses/export.csv` | GET | `backend/app/routes/expenses.py` | `exportCsv(month,category,timezone)` | query `month/category/timezone` | streaming `text/csv` | Session Token | `backend/tests/test_stats_filters.py`, smoke | gray/internal 导出 |
| `/api/expenses/manual` | POST | `backend/app/routes/expenses.py` | `createManualExpense(request)` | `ExpenseManualCreateRequest` | `ExpenseDto` | Session Token，owner/member 写权限 | `backend/tests/test_expenses.py` | gray/internal |
| `/api/expenses/notification-drafts` | POST | `backend/app/routes/expenses.py` | 后续 Android 通知草稿入口 | `NotificationDraftCreateRequest` | `ExpenseDto` | Session Token，owner/member 写权限 | `backend/tests/test_notification_drafts.py` | v0.6；结构化草稿，不上传通知原文 |
| `/api/expenses/{id}` | GET | `backend/app/routes/expenses.py` | 无 | path `id` | `ExpenseDto` | Session Token | `backend/tests/test_expenses.py` | internal/debug 读取详情 |
| `/api/expenses/{id}` | PATCH | `backend/app/routes/expenses.py` | `updateExpense(id,request)` | `ExpenseUpdateRequest` | `ExpenseDto` | Session Token | `backend/tests/test_expenses.py` | gray/internal |
| `/api/expenses/{id}/confirm` | POST | `backend/app/routes/expenses.py` | `confirmExpense(id)` | path `id` | `ExpenseDto` | Session Token | `backend/tests/test_expenses.py`, smoke | gray/internal |
| `/api/expenses/{id}/reject` | POST | `backend/app/routes/expenses.py` | `rejectExpense(id)` | path `id` | `ExpenseDto` | Session Token | `backend/tests/test_expenses.py`, smoke | gray/internal |
| `/api/expenses/{id}/ocr/retry` | POST | `backend/app/routes/expenses.py` | `retryOcr(id)` | path `id` | `ExpenseDto` | Session Token | `backend/tests/test_expenses.py` | internal/高级入口 |
| `/api/expenses/{id}/recognize-text` | POST | `backend/app/routes/expenses.py` | 无 | `RecognizeTextRequest` | `ExpenseDto` | Session Token | `backend/tests/test_expenses.py` | internal/shortcut text |
| `/api/expenses/{id}/mark-not-duplicate` | POST | `backend/app/routes/expenses.py` | `markNotDuplicate(id)` | path `id` | `ExpenseDto` | Session Token | `backend/tests/test_expenses.py` | gray/internal |
| `/api/expenses/{id}/image` | GET | `backend/app/routes/expenses.py` | `expenseImage(id)` | path `id` | streaming image | Session Token | `backend/tests/test_expenses.py`, smoke | gray/internal |
| `/api/expenses/{id}/thumbnail` | GET | `backend/app/routes/expenses.py` | `expenseThumbnail(id)` | path `id` | streaming image | Session Token | `backend/tests/test_expenses.py`, smoke | gray/internal |
| `/api/duplicates` | GET | `backend/app/routes/duplicates.py` | `duplicates()` | 无 | `List<ExpenseDto>` | Session Token | `backend/tests/test_expenses.py` | gray/internal |
| `/api/rules/categories` | GET | `backend/app/routes/rules.py` | `categoryRules()` | 无 | `List<CategoryRuleDto>` | Session Token | `backend/tests/test_expenses.py` | internal/高级入口 |
| `/api/rules/categories` | POST | `backend/app/routes/rules.py` | `createCategoryRule(request)` | `CategoryRuleRequest` | `CategoryRuleDto` | Session Token | `backend/tests/test_expenses.py` | internal/高级入口 |
| `/api/rules/categories/{id}` | PATCH | `backend/app/routes/rules.py` | `updateCategoryRule(id,request)` | `CategoryRuleRequest` | `CategoryRuleDto` | Session Token | `backend/tests/test_expenses.py` | internal/高级入口 |
| `/api/rules/categories/{id}` | DELETE | `backend/app/routes/rules.py` | `deleteCategoryRule(id)` | path `id` | `StatusDto` | Session Token | `backend/tests/test_expenses.py`, `ApiDtoContractTest` | internal/高级入口 |
| `/api/settings/server` | GET | `backend/app/routes/settings.py` | `serverSettings()` | 无 | `ServerSettingsDto` | Session Token | `backend/tests/test_maintenance.py` | gray/internal |
| `/api/stats/monthly` | GET | `backend/app/routes/stats.py` | `monthlyStats(month,timezone)` | query `month/timezone` | `MonthlyStatsDto` | Session Token | `backend/tests/test_stats_filters.py`, Android domain tests | gray/internal |
| `/api/stats/lifestyle` | GET | `backend/app/routes/stats.py` | `lifestyleStats(month,timezone)` | query `month/timezone` | `LifestyleStatsDto` | Session Token | `backend/tests/test_stats_filters.py` | gray/internal |
| `/api/recurring/items` | GET | `backend/app/routes/recurring.py` | `recurringItems(status,includeArchived,month,timezone)` | query `status/include_archived/month/timezone` | `RecurringItemListResponseDto` | Session Token | `backend/tests/test_recurring_items.py`, `ApiDtoContractTest` | v0.6 固定支出列表 |
| `/api/recurring/from-candidate` | POST | `backend/app/routes/recurring.py` | `confirmRecurringCandidate(request,timezone)` | `RecurringCandidateConfirmRequest`；query `timezone` | `RecurringItemDto` | Session Token，owner/member 写权限 | `backend/tests/test_recurring_items.py` | 候选确认成固定支出 |
| `/api/recurring/items/{public_id}` | GET | `backend/app/routes/recurring.py` | `recurringItem(publicId,month,timezone)` | path `public_id`；query `month/timezone` | `RecurringItemDto` | Session Token | `backend/tests/test_recurring_items.py` | 固定支出详情 |
| `/api/recurring/items/{public_id}/pause` | POST | `backend/app/routes/recurring.py` | `pauseRecurringItem(publicId)` | path `public_id` | `RecurringItemDto` | Session Token，owner/member 写权限 | `backend/tests/test_recurring_items.py` | 暂停固定支出 |
| `/api/recurring/items/{public_id}/resume` | POST | `backend/app/routes/recurring.py` | `resumeRecurringItem(publicId)` | path `public_id` | `RecurringItemDto` | Session Token，owner/member 写权限 | `backend/tests/test_recurring_items.py` | 恢复固定支出 |
| `/api/recurring/items/{public_id}/archive` | POST | `backend/app/routes/recurring.py` | `archiveRecurringItem(publicId)` | path `public_id` | `RecurringItemDto` | Session Token，owner/member 写权限 | `backend/tests/test_recurring_items.py` | 归档固定支出 |
| `/api/maintenance/cleanup-images` | POST | `backend/app/routes/maintenance.py` | 无 | 无 | `MaintenanceCleanupResponse` | Admin Token | `backend/tests/test_maintenance.py`, smoke | admin |
| `/api/maintenance/cleanup-rejected` | POST | `backend/app/routes/maintenance.py` | 无 | 无 | `MaintenanceCleanupResponse` | Admin Token | `backend/tests/test_maintenance.py`, smoke | admin |
| `/api/maintenance/cleanup-orphans` | POST | `backend/app/routes/maintenance.py` | 无 | query `dry_run` | `MaintenanceOrphanCleanupResponse` | Admin Token | `backend/tests/test_maintenance.py`, smoke | admin |
| `/api/admin/devices` | GET | `backend/app/routes/admin.py` | 无 | 无 | `List<AdminDeviceResponse>` | Admin Token | `backend/tests/test_admin_devices_and_upload_links.py` | admin 设备管理 |
| `/api/admin/devices/{public_id}/revoke` | POST | `backend/app/routes/admin.py` | 无 | path `public_id` | `AdminDeviceResponse` | Admin Token | `backend/tests/test_admin_devices_and_upload_links.py` | 停用设备并撤销其全部 token |
| `/api/admin/devices/{public_id}/rename` | POST | `backend/app/routes/admin.py` | 无 | `AdminDeviceRenameRequest` | `AdminDeviceResponse` | Admin Token | `backend/tests/test_admin_devices_and_upload_links.py` | admin 重命名设备 |
| `/api/admin/upload-links` | GET | `backend/app/routes/admin.py` | 无 | 无 | `List<AdminUploadLinkResponse>` | Admin Token | `backend/tests/test_admin_devices_and_upload_links.py` | 列出 UploadLink（链接掩码 `/u/***`） |
| `/api/admin/upload-links` | POST | `backend/app/routes/admin.py` | 无 | `AdminUploadLinkCreateRequest` | `AdminUploadLinkSecretResponse` | Admin Token | `backend/tests/test_admin_devices_and_upload_links.py` | 创建新的 UploadLink，仅返回一次完整 URL |
| `/api/admin/upload-links/{public_id}/rotate` | POST | `backend/app/routes/admin.py` | 无 | path `public_id` | `AdminUploadLinkSecretResponse` | Admin Token | `backend/tests/test_admin_devices_and_upload_links.py` | 轮换 UploadLink；旧 key 立即失效 |
| `/api/admin/upload-links/{public_id}/revoke` | POST | `backend/app/routes/admin.py` | 无 | path `public_id` | `AdminUploadLinkResponse` | Admin Token | `backend/tests/test_admin_devices_and_upload_links.py` | 立即停用 UploadLink |

## 基础接口

### GET /api/health

不需要 Token。只表示服务可达。

返回：

```json
{
  "status": "ok"
}
```

### GET /api/auth/check

请求头：

```http
Authorization: Bearer <session_token>
```

Android 首次绑定后校验 session token 使用。

返回：

```json
{
  "status": "ok",
  "account_name": "Owner",
  "ledger_id": "owner",
  "ledger_name": "我的小票夹",
  "device_name": "小米 15 Pro",
  "role": "owner",
  "scope": "app"
}
```

> v0.4-alpha1 起新增 `ledger_id`，对应当前会话激活的账本。

### POST /api/auth/pair

设备绑定接口，不需要鉴权。

请求体：

```json
{
  "pairing_code": "738294",
  "device_name": "小米 15 Pro",
  "platform": "Android"
}
```

返回：

```json
{
  "session_token": "tk_xxxxxx",
  "account_name": "Owner",
  "ledger_id": "owner",
  "ledger_name": "我的小票夹",
  "device_name": "小米 15 Pro",
  "role": "owner"
}
```

> v0.4-alpha1 起新增 `ledger_id`。

错误：

- `invalid_pairing_code`：绑定码不存在。
- `invalid_pairing_code` + HTTP 429：同一来源短时间内失败次数过多，稍后再试或重新生成绑定码。
- `pairing_code_used`：绑定码已被使用（一次性）。
- `pairing_code_expired`：绑定码已过期（默认 15 分钟）。

### GET /api/ledgers

> v0.4-alpha1 起提供。返回当前会话账号有权访问的账本。需要 session token。

```json
{
  "ledgers": [
    {"ledger_id": "owner", "name": "我的小票夹", "role": "owner", "is_default": true,
     "created_at": "2026-01-01T00:00:00Z", "archived_at": null}
  ]
}
```

### POST /api/ledgers

> v0.4-alpha1 起提供。新建账本，请求体 `{"name": "..."}`。

- 名称为空：返回 `validation_error` + `请填写账本名称`。
- 名称超过 60 字：返回 `validation_error` + `账本名称最多 60 个字`。

返回单个 `LedgerDto`。

### POST /api/ledgers/{ledger_id}/switch

> v0.4-alpha1 起提供。把当前会话切换到目标账本，**轮换** session token；旧 token 立即失效。

```json
{
  "session_token": "tk_yyyy",
  "ledger": {"ledger_id": "owner", "name": "我的小票夹", "role": "owner", "is_default": true,
             "created_at": "2026-01-01T00:00:00Z", "archived_at": null},
  "account_name": "Owner",
  "device_name": "小米 15 Pro"
}
```

错误：

- `forbidden` / `请选择一个有权限的账本`：调用方对该账本无成员关系。

### POST /api/ledgers/{ledger_id}/invitations

> v0.4-beta1 起提供。当前账本 owner 创建家庭账本邀请，返回的 `invite_token` 明文只显示一次。

请求头：

```http
Authorization: Bearer <owner_session_token>
```

请求体：

```json
{
  "role": "member",
  "note": "妈妈",
  "ttl_days": 7
}
```

`role` 只能是 `member` 或 `viewer`，不能通过邀请创建 owner。

### POST /api/invitations/accept

> v0.4-beta1 起提供。被邀请设备接受邀请，创建独立 Account / Device / LedgerMember，并签发新的 app session token。

请求体：

```json
{
  "invite_token": "inv_xxxxxx",
  "account_name": "妈妈",
  "device_name": "Pixel 8",
  "platform": "android"
}
```

返回结构与 pairing 类似，包含 `session_token`、`ledger_id`、`ledger_name`、`role`。

### GET /api/ledgers/{ledger_id}/members

> v0.4-beta1 起提供。当前账本任意活跃成员可查看成员列表。

### POST /api/ledgers/{ledger_id}/members/{member_id}/role

> v0.5 household hardening 起提供。当前账本 owner 可把活跃非 owner 成员在 `member` / `viewer` 之间调整。owner 转让不走此接口。

请求体：

```json
{
  "role": "viewer"
}
```

角色调整不改 token 明文、不重新签发 token；服务端在每次鉴权时从 `LedgerMember.role` 读取最新角色。

### POST /api/ledgers/{ledger_id}/members/{member_id}/disable

> v0.4-beta1 起提供。当前账本 owner 停用非 owner 成员，并吊销该成员在此账本下的活跃 token。

### POST /api/bootstrap/owner

Owner 初始化，仅首次可用，并且只接受后端本机 loopback 请求。公网请求会返回 `invalid_token`（403）。

请求体：

```json
{
  "account_name": "Owner",
  "ledger_name": "我的小票夹",
  "device_name": "Windows",
  "default_timezone": "Asia/Shanghai"
}
```

返回：

```json
{
  "account_name": "Owner",
  "ledger_id": "owner",
  "ledger_name": "我的小票夹",
  "device_name": "Windows",
  "admin_token": "tk_admin_xxxxxx",
  "upload_key": "up_xxxxxx",
  "upload_url_path": "/u/up_xxxxxx",
  "pairing_code": "738294",
  "pairing_expires_at": "2026-05-09T07:00:00Z"
}
```

错误：

- `bootstrap_already_initialized`：后端已有活跃身份数据，拒绝重复初始化。
- `invalid_token`：请求不是从后端本机发起。

### POST /api/bootstrap/pairing-codes

生成新的 Pairing Code，需要 admin token。

请求头：

```http
Authorization: Bearer <admin_token>
```

请求体：

```json
{
  "device_name_hint": "iPhone",
  "ttl_minutes": 15
}
```

返回：

```json
{
  "pairing_code": "529481",
  "ledger_name": "我的小票夹",
  "expires_at": "2026-05-09T07:15:00Z"
}
```

## 上传

### GET /api/upload/check

> **已废弃**：v0.3 不再提供 Upload Token 自检。旧版 `Upload-Token` header 请求返回 `legacy_auth_removed`；其他请求返回 `invalid_token`。Android 使用 `/api/auth/check` 和业务上传接口验证 session 是否有效。

### POST /api/upload-screenshot

> **已废弃**：v0.3 使用 UploadLink URL `POST /u/{upload_key}` 代替。旧 `Upload-Token` header 请求一律返回 `legacy_auth_removed`。

### POST /u/{upload_key}

iPhone 快捷指令上传入口。

URL 示例：

```text
POST https://api.我的域名.com/u/up_xxxxxx?tz=Asia/Shanghai
```

请求头：

```http
User-Agent: TicketBox/1.0 iOS-Shortcut
```

请求体方式一，iOS 快捷指令推荐，iOS 26.4 真机验证通过：

```text
raw image body
Content-Type: image/jpeg 或 image/png
X-Upload-Filename: 可选
```

请求体方式二，兼容标准表单：

```text
multipart/form-data
file: 图片文件
```

表单字段兼容顺序：

```text
file -> image -> photo -> screenshot -> 表单里的第一个文件字段
```

规则：

- 支持 `jpg`、`jpeg`、`png`、`webp`、`heic`。
- 同一个接口同时支持原始图片请求体和 `multipart/form-data` 文件字段。
- iOS 快捷指令优先使用原始图片请求体，也就是"请求正文：文件"。不要优先使用"请求正文：表单"。
- `?tz=...` 可选，填手机系统 IANA 时区；用于上传后 OCR 草稿的本地时间解析，未传时使用服务端 `OCR_DEFAULT_TIMEZONE`。
- Cloudflare 可能拦截没有标准 `User-Agent` 的快捷指令请求，公网部署时建议固定 `User-Agent`。
- 最大 10MB，按 `MAX_UPLOAD_SIZE_MB` 配置。
- 保存为随机文件名。
- 数据库只保存相对路径。
- 计算 `image_hash`。
- 生成 pending 账单。
- 尝试生成 JPEG 缩略图；当前 HEIC 会保存原图但跳过缩略图生成。
- 检测完全相同 `image_hash`，只标记疑似重复，不自动拒绝。
- 用户补充 `amount_cents`、`merchant`、`expense_time` 后，会额外检测同金额、同商家、24 小时内的相似账单。

返回：

```json
{
  "id": 1,
  "public_id": "018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d",
  "status": "pending",
  "message": "uploaded",
  "image_hash": "sha256...",
  "thumbnail_path": "uploads/owner/2026/05/thumbs/xxx.jpg",
  "duplicate_status": "none",
  "duplicate_of_id": null,
  "upload_size_bytes": 348120,
  "duration_ms": 86,
  "timing_ms": {
    "body_read_ms": 12,
    "file_save_ms": 18,
    "db_create_ms": 24,
    "total_ms": 86
  }
}
```

`timing_ms` 用于运维排查上传慢的问题。原始图片请求体通常包含 `body_read_ms`，表单上传通常包含 `form_parse_ms`。普通 App 不需要展示这些字段。

### POST /api/app/upload-screenshot

Android App 自带上传入口使用。

请求头：

```http
Authorization: Bearer <session_token>
```

请求体：

```text
multipart/form-data
file: 图片文件
```

规则：

- 与 iPhone 上传共用同一套文件校验、随机命名、hash、缩略图和 pending 创建流程。
- 按当前 session token 所属账本写入对应目录。
- 仅 `owner` / `member` 可上传；`viewer` 返回 `permission_denied` + `当前角色为只读，无法修改账本。`。
- `X-Timezone` 可选，Android 默认发送手机系统 IANA 时区；用于上传后 OCR 草稿时间解析。
- Android 不保存、不发送 UploadLink。
- 灰度版 UI 只显示"上传截图"，不显示 endpoint、token 或 multipart。

返回：

```json
{
  "id": 1,
  "public_id": "018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d",
  "status": "pending",
  "message": "uploaded",
  "image_hash": "sha256...",
  "thumbnail_path": "uploads/owner/2026/05/thumbs/xxx.jpg",
  "duplicate_status": "none",
  "duplicate_of_id": null,
  "upload_size_bytes": 348120,
  "duration_ms": 86,
  "timing_ms": {
    "form_parse_ms": 8,
    "file_save_ms": 18,
    "db_create_ms": 24,
    "total_ms": 86
  }
}
```

## 账单

### GET /api/expenses/pending

请求头：

```http
Authorization: Bearer <session_token>
```

返回 pending 账单列表。

### POST /api/expenses/manual

请求头：

```http
Authorization: Bearer <session_token>
```

用于 Android App 手动记一笔，创建后直接进入已确认账本。

请求体：

```json
{
  "amount_cents": 1280,
  "merchant": "便利店",
  "category": "生活",
  "note": "上班路上",
  "expense_time": "2026-05-04T00:30:00Z"
}
```

规则：

- `amount_cents` 必填，单位为分。
- `expense_time` 可为空；为空时后端使用确认时间。
- `source` 固定为 `手动记账`。
- `status` 固定为 `confirmed`。
- 不保存图片路径，不暴露本机路径。

### POST /api/expenses/notification-drafts

请求头：

```http
Authorization: Bearer <session_token>
Content-Type: application/json
```

用于 v0.6 Android 通知监听后的结构化草稿创建。只允许上传解析后的结构化字段，不接受通知原文；创建结果固定为 `pending`，后续仍需用户确认入账。

请求体：

```json
{
  "source": "wechat",
  "merchant": "星巴克",
  "amount_cents": 2680,
  "category": "餐饮",
  "expense_time": "2026-05-13T10:05:00Z"
}
```

规则：

- `source` 仅支持 `wechat` / `alipay` / `bank_sms` / `bank_app` / `other`。
- 请求体禁止 `raw_text` 等原文类字段；校验失败返回 `invalid_request`。
- 后端按当前账本、来源、商家、金额、30 分钟时间窗口计算幂等键；重复请求返回同一条草稿，不重复生成 pending。
- `viewer` 返回 `permission_denied`。
- 不保存图片路径，不自动确认，不更新固定支出记录。

### GET /api/expenses/confirmed

请求头：

```http
Authorization: Bearer <session_token>
```

查询参数：

```text
page: 默认 1
page_size: 默认 50，最大 200
month: YYYY-MM，可选
category: 分类，可选
timezone: IANA 时区名，可选；Android 默认传手机系统时区，未传时使用服务端 OCR_DEFAULT_TIMEZONE
```

返回：

```json
{
  "items": [],
  "page": 1,
  "page_size": 50,
  "total": 0
}
```

### GET /api/expenses/categories

请求头：

```http
Authorization: Bearer <session_token>
```

返回标准默认分类和数据库中已有分类。旧版 `吃饭` 会兼容归一到 `餐饮`。

返回：

```json
{
  "items": ["餐饮", "交通", "购物", "娱乐", "医疗", "教育", "住房", "通讯", "AI订阅", "数码", "游戏", "生活", "其他"]
}
```

### GET /api/expenses/months

请求头：

```http
Authorization: Bearer <session_token>
```

查询参数：

```text
timezone: IANA 时区名，可选；Android 默认传手机系统时区，未传时使用服务端 OCR_DEFAULT_TIMEZONE
```

返回已确认账单中出现过的月份，按新到旧排序。月份按 `timezone` 对应的本地自然月计算，统计和账本页可用它做月份快捷选择。

返回：

```json
{
  "items": ["2026-05", "2026-04"]
}
```

### GET /api/expenses/export.csv

请求头：

```http
Authorization: Bearer <session_token>
```

查询参数：

```text
month: YYYY-MM，可选
category: 分类，可选
timezone: IANA 时区名，可选；Android 默认传手机系统时区，未传时使用服务端 OCR_DEFAULT_TIMEZONE
```

返回 `text/csv`，用于导出已确认账单。导出接口只返回账单数据，不提供文件目录浏览或任意文件下载。

### PATCH /api/expenses/{id}

请求头：

```http
Authorization: Bearer <session_token>
Content-Type: application/json
```

请求体：

```json
{
  "amount_cents": 3680,
  "merchant": "美团外卖",
  "category": "餐饮",
  "note": "午饭",
  "expense_time": "2026-05-03T04:20:00Z",
  "tags": "真香",
  "value_score": 5,
  "regret_score": 1
}
```

只能修改 `pending` 或 `confirmed`。

### GET /api/expenses/{id}

请求头：

```http
Authorization: Bearer <session_token>
```

返回单条账单详情，响应结构同 `ExpenseResponse`。找不到返回 `expense_not_found`。

### POST /api/expenses/{id}/confirm

请求头：

```http
Authorization: Bearer <session_token>
```

规则：

- `amount_cents` 为空时返回 `amount_required`。
- 状态改为 `confirmed`。
- 写入 `confirmed_at` 和 `updated_at`。
- 按配置执行确认后图片清理策略。

### POST /api/expenses/{id}/reject

请求头：

```http
Authorization: Bearer <session_token>
```

只能拒绝 `pending`。

### GET /api/expenses/{id}/image

请求头：

```http
Authorization: Bearer <session_token>
```

返回原图文件流。不会返回本机真实路径。

### GET /api/expenses/{id}/thumbnail

请求头：

```http
Authorization: Bearer <session_token>
```

返回 JPEG 缩略图文件流。缩略图不存在时会尝试懒生成；仍不可用返回 `image_not_found`。

### POST /api/expenses/{id}/ocr/retry

请求头：

```http
Authorization: Bearer <session_token>
```

重新运行当前 `OCR_PROVIDER`。OCR 只写入待确认草稿，不会自动入账。

支持的 provider：

```text
empty
mock
rapidocr
local_llm
```

写入策略：

- 更新 `raw_text` 和 `confidence`。
- 仅当 `amount_cents`、`merchant`、`expense_time` 仍为空时才自动填充。
- 仅当分类仍为 `其他` 时才自动分类。
- 写入金额、商家或消费时间后，会重新计算疑似重复状态。

### POST /api/expenses/{id}/recognize-text

请求头：

```http
Authorization: Bearer <session_token>
```

请求体：

```json
{
  "raw_text": "中国建设银行\n交易时间：2026年5月4日 16:23:25\n交易金额：18.51（人民币）"
}
```

行为：

- 从文本规则中提取 `amount_cents`、`merchant`、`expense_time`、`category` 和 `confidence`。
- 保存 `raw_text`。
- 不自动确认入账。

### POST /api/expenses/{id}/mark-not-duplicate

请求头：

```http
Authorization: Bearer <session_token>
```

清除疑似重复标记，并记录这组账单在当前检测类型下的"非重复"判断。图片 hash 重复和金额/商家/时间相似会分别记录，互不覆盖。

## 重复检测

### GET /api/duplicates

请求头：

```http
Authorization: Bearer <session_token>
```

返回 `duplicate_status = suspected` 且未被拒绝的账单列表。

当前已支持两类提示：

- 图片 `image_hash` 完全一致。
- 金额一致、商家一致、消费时间或确认时间相差 24 小时内。

重复检测只提示，不自动拒绝或删除账单。用户调用 `POST /api/expenses/{id}/mark-not-duplicate` 后，这组账单在当前检测类型下会被忽略。

## 分类规则

### GET /api/rules/categories

请求头：

```http
Authorization: Bearer <session_token>
```

返回自动分类规则列表。

### POST /api/rules/categories

请求头：

```http
Authorization: Bearer <session_token>
```

请求体：

```json
{
  "keyword": "OpenAI",
  "category": "AI订阅",
  "enabled": true,
  "priority": 5
}
```

仅 `owner` / `member` 可新增、修改、删除或应用分类规则；`viewer` 对这些写入口返回：

```json
{
  "error": "permission_denied",
  "message": "当前角色为只读，无法修改账本。"
}
```

### PATCH /api/rules/categories/{id}

请求头：

```http
Authorization: Bearer <session_token>
```

请求体支持局部更新：

```json
{
  "enabled": false
}
```

### DELETE /api/rules/categories/{id}

请求头：

```http
Authorization: Bearer <session_token>
```

删除一条分类规则。

返回：

```json
{
  "status": "ok"
}
```

## 设置

### GET /api/settings/server

请求头：

```http
Authorization: Bearer <session_token>
```

返回后端非敏感运行状态，不返回 Token、本机路径或数据库路径。
`upload_storage_bytes` 只统计当前 session token 对应账本目录下仍存在的图片和缩略图文件。

返回：

```json
{
  "account_name": "Owner",
  "ledger_id": "owner",
  "ledger_name": "我的小票夹",
  "ledger_is_default": true,
  "device_name": "小米 15 Pro",
  "role": "owner",
  "status": "ok",
  "storage_status": "normal",
  "pending_count": 1,
  "confirmed_count": 2,
  "rejected_count": 0,
  "suspected_duplicate_count": 0,
  "upload_storage_bytes": 123456,
  "latest_upload_at": "2026-05-05T09:20:00Z"
}
```

## 统计

### GET /api/stats/monthly

请求头：

```http
Authorization: Bearer <session_token>
```

查询参数：

```text
month=2026-05
timezone=Asia/Shanghai
```

返回：

```json
{
  "month": "2026-05",
  "total_amount_cents": 123456,
  "count": 30,
  "by_category": [
    {
      "category": "餐饮",
      "amount_cents": 52050,
      "count": 18
    }
  ]
}
```

### GET /api/stats/lifestyle

请求头：

```http
Authorization: Bearer <session_token>
```

查询参数：

```text
month=2026-05
timezone=Asia/Shanghai
```

返回：

```json
{
  "month": "2026-05",
  "ai_subscription_amount_cents": 2000,
  "digital_amount_cents": 0,
  "max_expense": null,
  "recent_7_days_amount_cents": 2000,
  "frequent_merchants": [
    {
      "merchant": "OpenAI",
      "count": 1
    }
  ]
}
```

## 固定支出

> v0.6 起提供。固定支出由用户从 recurring candidates 手动确认生成；不会自动入账，也不会自动创建 pending。

### GET /api/recurring/items

请求头：

```http
Authorization: Bearer <session_token>
```

查询参数：

```text
status=active|paused|archived，可选
include_archived=true|false，默认 false
month=YYYY-MM，可选，用于异常金额检测；未传时按当前月
timezone=Asia/Shanghai，可选
```

返回：

```json
{
  "items": [
    {
      "public_id": "recurring-1",
      "ledger_id": "owner",
      "merchant": "ChatGPT Plus",
      "merchant_key": "chatgpt plus",
      "frequency": "monthly",
      "baseline_amount_cents": 20000,
      "last_amount_cents": 20000,
      "occurrence_count": 3,
      "last_seen_at": "2026-05-05T12:00:00Z",
      "next_expected_date": "2026-06-05",
      "status": "active",
      "confidence": "high",
      "source": "candidate",
      "anomaly_status": "none",
      "current_month_amount_cents": 20000,
      "historical_average_amount_cents": 20000,
      "amount_delta_percent": 0,
      "created_at": "2026-05-13T00:00:00Z",
      "updated_at": "2026-05-13T00:00:00Z",
      "paused_at": null,
      "archived_at": null
    }
  ]
}
```

### POST /api/recurring/from-candidate

把当前账本内仍然有效的 recurring candidate 确认为正式固定支出。仅 `owner` / `member` 可调用，`viewer` 返回 `permission_denied`。

```json
{
  "merchant": "ChatGPT Plus",
  "amount_cents": 20000,
  "occurrence_count": 3,
  "last_seen_at": "2026-05-05T12:00:00Z",
  "confidence": "high",
  "frequency": "monthly",
  "next_expected_date": "2026-06-05"
}
```

同一账本、商家归一名和频率重复确认时返回既有记录，不重复创建。

异常金额检测只在读取 recurring items 时计算，不更新账单、不更新固定支出记录，也不自动生成 pending。当前口径：指定月份内该商家最新一笔金额比历史均值高 30% 或以上时，`anomaly_status = "higher_than_average"`。

### GET /api/recurring/items/{public_id}

读取当前账本内的固定支出详情。跨账本读取返回 `recurring_item_not_found`。

### POST /api/recurring/items/{public_id}/pause
### POST /api/recurring/items/{public_id}/resume
### POST /api/recurring/items/{public_id}/archive

固定支出状态机：

```text
active -> paused
paused -> active
active/paused -> archived
archived 不允许恢复或暂停
```

## 维护

### POST /api/maintenance/cleanup-images

请求头：

```http
Authorization: Bearer <admin_token>
```

规则：

- 只按 `DELETE_IMAGE_AFTER_DAYS` 配置清理已确认账单图片。
- 不接收任意文件路径。
- 只删除数据库中保存的相对路径，且路径必须位于当前 admin 上下文账本的 `uploads/{ledger_id}/` 目录内。
- `DELETE_IMAGE_AFTER_DAYS <= 0` 时只返回未启用，不执行删除。

返回：

```json
{
  "enabled": false,
  "delete_after_days": 0,
  "scanned": 0,
  "deleted_images": 0,
  "deleted_thumbnails": 0
}
```

### POST /api/maintenance/cleanup-rejected

请求头：

```http
Authorization: Bearer <admin_token>
```

规则：

- 只按 `DELETE_REJECTED_AFTER_DAYS` 配置清理 rejected 账单图片。
- 只清理图片和缩略图，不删除 rejected 数据库行。
- 只删除当前 admin 上下文账本目录内的文件。
- `DELETE_REJECTED_AFTER_DAYS <= 0` 时只返回未启用，不执行删除。

返回：

```json
{
  "enabled": false,
  "delete_after_days": 0,
  "scanned": 0,
  "deleted_images": 0,
  "deleted_thumbnails": 0
}
```

### POST /api/maintenance/cleanup-orphans

请求头：

```http
Authorization: Bearer <admin_token>
```

查询参数：

- `dry_run=true`：只扫描，不删除，默认值。
- `dry_run=false`：删除超过保护窗口的孤儿 uploads 文件。

规则：

- 只扫描当前 admin 上下文账本目录内支持的图片文件。
- 只处理数据库没有引用的文件。
- 使用 `ORPHAN_UPLOAD_GRACE_HOURS` 保护最近上传文件。
- 不接收任意文件路径。

返回：

```json
{
  "dry_run": true,
  "grace_hours": 24,
  "scanned_files": 10,
  "orphan_files": 1,
  "deleted_files": 0,
  "orphan_bytes": 12345,
  "deleted_bytes": 0
}
```
