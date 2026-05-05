# 多租户隔离规格

日期：2026-05-05

## 1. 目标

灰度版要支持把小票夹发给别人试用。不同灰度用户之间不能互相看到账单、图片、统计、分类规则和重复检测结果。

第一版多租户不做账号密码、不做注册登录、不做复杂后台，只做配置式租户。

## 2. 配置

推荐配置：

```env
TENANTS_JSON=[
  {"id":"owner","name":"我的小票夹","upload_token":"...","app_token":"..."},
  {"id":"tester_1","name":"灰度用户1","upload_token":"...","app_token":"..."}
]
```

兼容旧单用户配置：

```env
UPLOAD_TOKEN=...
APP_TOKEN=...
ADMIN_TOKEN=...
```

兼容规则：

- 未配置 `TENANTS_JSON` 时，自动使用旧配置生成默认租户。
- 默认租户 id 为 `owner`。
- 默认租户 name 为 `我的小票夹`。
- 旧数据自动归到 `owner`。
- 不破坏现有个人使用。

## 3. 后端新增概念

需要新增：

- 租户配置解析。
- `TenantContext`。
- `get_current_app_tenant()`。
- `get_current_upload_tenant()`。
- `get_current_admin_context()`。

上下文规则：

- Upload Token 只能得到上传租户。
- App Token 只能得到 App 租户。
- Admin Token 用于服务拥有者运维，不代表普通用户。
- routes 层只负责认证并把租户传给 service。
- service 层所有查询和写入必须带租户过滤。

## 4. 数据库字段

新增字段：

```text
Expense.tenant_id: string
CategoryRule.tenant_id: string
DuplicateIgnore.tenant_id: string
```

迁移规则：

- 老库新增字段后，旧数据全部写入 `owner`。
- `tenant_id` 不允许为空。
- 新建 Expense、CategoryRule、DuplicateIgnore 时必须显式写入当前租户。

索引：

```text
expenses(tenant_id, status, created_at)
expenses(tenant_id, status, expense_time)
expenses(tenant_id, status, confirmed_at)
expenses(tenant_id, status, category, expense_time)
expenses(tenant_id, status, category, confirmed_at)
expenses(tenant_id, image_hash)
expenses(tenant_id, duplicate_status)
category_rules(tenant_id, priority, id)
duplicate_ignores(tenant_id, expense_id, duplicate_of_id, kind)
```

## 5. 必须租户化的接口

以下接口必须按租户过滤：

```text
GET /api/expenses/pending
GET /api/expenses/confirmed
GET /api/expenses/{id}
PATCH /api/expenses/{id}
POST /api/expenses/{id}/confirm
POST /api/expenses/{id}/reject
GET /api/expenses/{id}/image
GET /api/expenses/{id}/thumbnail
POST /api/expenses/{id}/ocr/retry
POST /api/expenses/{id}/recognize-text
POST /api/expenses/{id}/mark-not-duplicate
GET /api/stats/monthly
GET /api/stats/lifestyle
GET /api/rules/categories
POST /api/rules/categories
PATCH /api/rules/categories/{id}
DELETE /api/rules/categories/{id}
GET /api/duplicates
GET /api/settings/server
GET /api/expenses/export.csv
POST /api/app/upload-screenshot
POST /api/upload-screenshot
```

## 6. 上传规则

iOS 快捷指令：

```http
POST /api/upload-screenshot
Upload-Token: <tenant upload token>
```

Android App：

```http
POST /api/app/upload-screenshot
Authorization: Bearer <tenant app token>
```

两者行为一致：

- 保存截图。
- 生成缩略图。
- 计算 image_hash。
- 创建当前租户的 pending 账单。
- 运行 OCR 草稿。
- 运行当前租户内的重复检测。
- 不自动确认入账。

## 7. 重复检测

重复检测不得跨租户。

同图 hash 检测：

```text
same tenant_id
same image_hash
status != rejected
```

相似账单检测：

```text
same tenant_id
same amount_cents
same merchant
expense_time/confirmed_at within 24h
status != rejected
```

`DuplicateIgnore` 也必须带 `tenant_id`。

## 8. 分类规则

分类规则必须按租户隔离。

- 默认规则可以给每个租户 seed 一份。
- 用户新增规则只影响当前租户。
- `tester_1` 新增规则不能影响 `owner`。

## 9. 设置摘要

`GET /api/settings/server` 面向 Android App 时只返回当前租户和用户可理解的摘要。

允许返回：

- `tenant_name`
- pending 数量
- confirmed 数量
- 最近上传时间
- 最近同步相关摘要
- OCR 是否启用的用户化描述

不返回：

- token
- 本机路径
- 端口
- 数据库路径
- Cloudflare 细节
- 进程信息

Windows 诊断脚本可以显示运维摘要，但不得打印 token。

## 10. 测试要求

必须新增测试：

- `tester_1` 看不到 `owner` 的 pending。
- `tester_1` 看不到 `owner` 的 confirmed。
- `tester_1` 无法下载 `owner` 的 image。
- `tester_1` 无法下载 `owner` 的 thumbnail。
- `tester_1` 统计不包含 `owner` 数据。
- `tester_1` CSV 不包含 `owner` 数据。
- `tester_1` 分类规则不影响 `owner`。
- 重复检测不跨租户。
- iOS upload_token 进入正确租户。
- Android app_token 上传到正确租户。
- 未配置 `TENANTS_JSON` 时旧单用户配置仍然可用。

## 11. 禁止事项

- 禁止在 service 层忘记租户过滤。
- 禁止用前端过滤代替后端隔离。
- 禁止普通用户通过 id 猜测访问其他租户账单。
- 禁止图片接口只按文件路径读取而不校验账单租户。
- 禁止 CSV 导出跨租户。
