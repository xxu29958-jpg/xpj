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

金额：

- 全链路使用 `amount_cents`。
- 单位为分。
- 不使用 float/double 保存金额。

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
file_too_large
unsupported_file_type
expense_not_found
amount_required
image_not_found
rule_not_found
server_error
invalid_request
```

## 认证

上传截图：

```http
Upload-Token: UPLOAD_TOKEN
```

App 接口：

```http
Authorization: Bearer APP_TOKEN
```

维护接口：

```http
Authorization: Bearer ADMIN_TOKEN
```

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
Authorization: Bearer APP_TOKEN
```

Android 首次绑定服务器时使用。

返回：

```json
{
  "status": "ok"
}
```

## 上传

### GET /api/upload/check

请求头：

```http
Upload-Token: UPLOAD_TOKEN
```

用于 iPhone 快捷指令联调，确认公网域名、Cloudflare Tunnel、后端服务和 `UPLOAD_TOKEN` 都正常。

返回：

```json
{
  "status": "ok",
  "max_upload_size_mb": 10,
  "supported_file_types": ["heic", "jpeg", "jpg", "png", "webp"],
  "recommended_body": "file"
}
```

### POST /api/upload-screenshot

请求头：

```http
Upload-Token: UPLOAD_TOKEN
```

请求体方式一，iOS 快捷指令推荐：

```text
raw image body
Content-Type: image/jpeg 或 image/png
```

请求体方式二，兼容标准表单：

```text
multipart/form-data
file: 图片文件
```

规则：

- 支持 `jpg`、`jpeg`、`png`、`webp`、`heic`。
- 同一个接口同时支持原始图片请求体和 `multipart/form-data` 表单字段 `file`。
- 最大 10MB，按 `MAX_UPLOAD_SIZE_MB` 配置。
- 保存为随机文件名。
- 数据库只保存相对路径。
- 计算 `image_hash`。
- 生成 pending 账单。
- 尝试生成 JPEG 缩略图，HEIC 第一版可能无缩略图。
- 检测完全相同 `image_hash`，只标记疑似重复，不自动拒绝。
- 用户补充 `amount_cents`、`merchant`、`expense_time` 后，会额外检测同金额、同商家、24 小时内的相似账单。

返回：

```json
{
  "id": 1,
  "status": "pending",
  "message": "uploaded"
}
```

## 账单

### GET /api/expenses/pending

请求头：

```http
Authorization: Bearer APP_TOKEN
```

返回 pending 账单列表。

### POST /api/expenses/manual

请求头：

```http
Authorization: Bearer APP_TOKEN
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

### GET /api/expenses/confirmed

请求头：

```http
Authorization: Bearer APP_TOKEN
```

查询参数：

```text
page: 默认 1
page_size: 默认 50，最大 200
month: YYYY-MM，可选
category: 分类，可选
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
Authorization: Bearer APP_TOKEN
```

返回默认分类和数据库中已有分类。

返回：

```json
{
  "items": ["吃饭", "数码", "生活", "交通", "游戏", "AI订阅", "购物", "娱乐", "医疗", "其他"]
}
```

### GET /api/expenses/months

请求头：

```http
Authorization: Bearer APP_TOKEN
```

返回已确认账单中出现过的月份，按新到旧排序。统计和账本页可用它做月份快捷选择。

返回：

```json
{
  "items": ["2026-05", "2026-04"]
}
```

### GET /api/expenses/export.csv

请求头：

```http
Authorization: Bearer APP_TOKEN
```

查询参数：

```text
month: YYYY-MM，可选
category: 分类，可选
```

返回 `text/csv`，用于导出已确认账单。导出接口只返回账单数据，不提供文件目录浏览或任意文件下载。

### PATCH /api/expenses/{id}

请求头：

```http
Authorization: Bearer APP_TOKEN
Content-Type: application/json
```

请求体：

```json
{
  "amount_cents": 3680,
  "merchant": "美团外卖",
  "category": "吃饭",
  "note": "午饭",
  "expense_time": "2026-05-03T04:20:00Z",
  "tags": "真香",
  "value_score": 5,
  "regret_score": 1
}
```

只能修改 `pending` 或 `confirmed`。

### POST /api/expenses/{id}/confirm

请求头：

```http
Authorization: Bearer APP_TOKEN
```

规则：

- `amount_cents` 为空时返回 `amount_required`。
- 状态改为 `confirmed`。
- 写入 `confirmed_at` 和 `updated_at`。
- 按配置执行确认后图片清理策略。

### POST /api/expenses/{id}/reject

请求头：

```http
Authorization: Bearer APP_TOKEN
```

只能拒绝 `pending`。

### GET /api/expenses/{id}/image

请求头：

```http
Authorization: Bearer APP_TOKEN
```

返回原图文件流。不会返回本机真实路径。

### GET /api/expenses/{id}/thumbnail

请求头：

```http
Authorization: Bearer APP_TOKEN
```

返回 JPEG 缩略图文件流。缩略图不存在时会尝试懒生成；仍不可用返回 `image_not_found`。

### POST /api/expenses/{id}/ocr/retry

请求头：

```http
Authorization: Bearer APP_TOKEN
```

第一版使用空 OCR provider，只保留可插拔入口，不做真实 OCR。

### POST /api/expenses/{id}/mark-not-duplicate

请求头：

```http
Authorization: Bearer APP_TOKEN
```

清除疑似重复标记，并记录这组账单在当前检测类型下的“非重复”判断。图片 hash 重复和金额/商家/时间相似会分别记录，互不覆盖。

## 重复检测

### GET /api/duplicates

请求头：

```http
Authorization: Bearer APP_TOKEN
```

返回 `duplicate_status = suspected` 的账单列表。

第一版已支持两类提示：

- 图片 `image_hash` 完全一致。
- 金额一致、商家一致、消费时间或确认时间相差 24 小时内。

重复检测只提示，不自动拒绝或删除账单。用户调用 `POST /api/expenses/{id}/mark-not-duplicate` 后，这组账单在当前检测类型下会被忽略。

## 分类规则

### GET /api/rules/categories

返回自动分类规则列表。

### POST /api/rules/categories

请求体：

```json
{
  "keyword": "OpenAI",
  "category": "AI订阅",
  "enabled": true,
  "priority": 5
}
```

### PATCH /api/rules/categories/{id}

请求体支持局部更新：

```json
{
  "enabled": false
}
```

### DELETE /api/rules/categories/{id}

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
Authorization: Bearer APP_TOKEN
```

返回后端非敏感运行状态，不返回 Token、本机路径或数据库路径。

返回：

```json
{
  "max_upload_size_mb": 10,
  "generate_thumbnail": true,
  "delete_image_after_confirm": false,
  "delete_image_after_days": 0,
  "ocr_provider": "empty",
  "pending_count": 1,
  "confirmed_count": 2,
  "rejected_count": 0,
  "suspected_duplicate_count": 0,
  "upload_storage_bytes": 123456
}
```

## 统计

### GET /api/stats/monthly

查询参数：

```text
month=2026-05
```

返回：

```json
{
  "month": "2026-05",
  "total_amount_cents": 123456,
  "count": 30,
  "by_category": [
    {
      "category": "吃饭",
      "amount_cents": 52050,
      "count": 18
    }
  ]
}
```

### GET /api/stats/lifestyle

查询参数：

```text
month=2026-05
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

## 维护

### POST /api/maintenance/cleanup-images

请求头：

```http
Authorization: Bearer ADMIN_TOKEN
```

规则：

- 只按 `DELETE_IMAGE_AFTER_DAYS` 配置清理已确认账单图片。
- 不接收任意文件路径。
- 只删除数据库中保存的相对路径，且路径必须位于 `uploads` 目录内。
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
