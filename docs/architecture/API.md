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

- `amount_cents` 是后端权威计算后的 home amount minor 字段；当前默认 home currency 为 `CNY`，历史字段名保持不变以兼容旧数据。
- 统计、预算、报表、Goals 均只汇总后端返回的 home amount，不直接相加外币原始金额。
- 单笔外币账单保存原始金额快照和当时汇率快照：`original_currency_code`、`original_amount_minor`、`exchange_rate_to_cny`、`exchange_rate_date`、`exchange_rate_source`。
- 新客户端提交账单时只提交 `original_currency`、`original_amount`、`spent_at` 和用户确认信息；不得提交汇率，不得自行折算 home amount。
- 旧客户端只传 `amount_cents` 时，后端按当前 home currency 原始金额和 `rate=1` 兼容。
- 汇率缺失时后端返回 `fx_status=pending`，不得由前端默认 1:1。
- 不使用 float/double 保存金额。

标识：

- 后端自增 `id` 仍用于当前 API 路径，例如 `/api/expenses/{id}`。
- `public_id` 是账单公共 UUID，用于导出、跨端同步、排查问题和未来多端合并。
- Android Room 同时保存 `serverId` 和 `publicId`；`publicId` 必须全局唯一，`serverId` 必须在当前 `ledgerId` 下唯一。
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
amount_invalid
currency_not_supported
exchange_rate_required
exchange_rate_invalid
exchange_rate_base_currency
image_not_found
rule_not_found
import_batch_not_found
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

1. 用户向服务拥有者索要 8 位 Pairing Code。
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
| `/api/expenses/confirmed` | GET | `backend/app/routes/expenses.py` | `confirmedExpenses(page,pageSize,month,category,timezone)` | query `page/page_size/month/category/tag/timezone` | `PaginatedExpensesDto` | Session Token | `backend/tests/test_stats_filters.py`, `backend/tests/test_tags.py`, Android domain tests | gray/internal |
| `/api/expenses/confirmed/batch-update` | POST | `backend/app/routes/expenses.py` | 无 | `ConfirmedExpenseBatchUpdateRequest` | `ConfirmedExpenseBatchUpdateResponse` | Session Token，owner/member 写权限 | `backend/tests/test_expenses.py` | 已入账账单分类/标签批处理 |
| `/api/expenses/categories` | GET | `backend/app/routes/expenses.py` | `categories()` | 无 | `CategoriesDto` | Session Token | `backend/tests/test_stats_filters.py` | gray/internal |
| `/api/expenses/tags` | GET | `backend/app/routes/expenses.py` | 无 | 无 | `TagsResponse` | Session Token | `backend/tests/test_tags.py` | v0.7 标签列表 |
| `/api/expenses/months` | GET | `backend/app/routes/expenses.py` | `months(timezone)` | query `timezone` | `MonthsDto` | Session Token | `backend/tests/test_stats_filters.py` | gray/internal |
| `/api/expenses/export.csv` | GET | `backend/app/routes/expenses.py` | `exportCsv(month,category,timezone)` | query `month/category/tag/timezone` | streaming `text/csv` | Session Token | `backend/tests/test_stats_filters.py`, `backend/tests/test_tags.py`, smoke | gray/internal 导出 |
| `/api/exchange-rates` | GET | `backend/app/routes/exchange_rates.py` | 无 | query `currency_code/limit` | `ExchangeRateListDto` | Session Token | `backend/tests/test_exchange_rates.py` | 每账本每日汇率，viewer 可读；Android 不直接读写汇率 |
| `/api/exchange-rates/{currency_code}/{rate_date}` | PUT | `backend/app/routes/exchange_rates.py` | 无 | `ExchangeRateRequest` | `ExchangeRateDto` | Session Token，owner/member 写权限 | `backend/tests/test_exchange_rates.py` | 后端维护/人工修正入口；客户端记账不得提交汇率 |
| `/api/imports/csv` | POST | `backend/app/routes/imports.py` | 无 | multipart `csv_file` | `CsvImportBatchResponse` | Session Token，owner/member 写权限 | `backend/tests/test_csv_import_batches.py` | v1.0 大 CSV 导入批次创建 |
| `/api/imports/csv/{public_id}` | GET | `backend/app/routes/imports.py` | 无 | path `public_id` | `CsvImportBatchResponse` | Session Token | `backend/tests/test_csv_import_batches.py` | v1.0 导入批次状态 |
| `/api/imports/csv/{public_id}/rows` | GET | `backend/app/routes/imports.py` | 无 | query `page/page_size/status` | `CsvImportRowsResponse` | Session Token | `backend/tests/test_csv_import_batches.py` | v1.0 导入行分页预览 |
| `/api/imports/csv/{public_id}/apply` | POST | `backend/app/routes/imports.py` | 无 | `CsvImportApplyRequest` | `CsvImportApplyResponse` | Session Token，owner/member 写权限 | `backend/tests/test_csv_import_batches.py` | v1.0 分批写入待确认账单 |
| `/api/imports/csv/{public_id}/errors.csv` | GET | `backend/app/routes/imports.py` | 无 | path `public_id` | streaming `text/csv` | Session Token | `backend/tests/test_csv_import_batches.py` | v1.0 下载导入错误行 |
| `/api/expenses/manual` | POST | `backend/app/routes/expenses.py` | `createManualExpense(request)` | `ExpenseManualCreateRequest` | `ExpenseDto` | Session Token，owner/member 写权限 | `backend/tests/test_expenses.py` | gray/internal |
| `/api/expenses/notification-drafts` | POST | `backend/app/routes/expenses.py` | `createNotificationDraft(request)` | `NotificationDraftCreateRequest` / `NotificationDraftRequestDto` | `ExpenseDto` | Session Token，owner/member 写权限 | `backend/tests/test_notification_drafts.py`, `ApiDtoContractTest`, `ExpenseRepositoryBindingTest` | v0.6；结构化草稿，不上传通知原文 |
| `/api/expenses/{id}` | GET | `backend/app/routes/expenses.py` | 无 | path `id` | `ExpenseDto` | Session Token | `backend/tests/test_expenses.py` | internal/debug 读取详情 |
| `/api/expenses/{id}/items` | GET | `backend/app/routes/expenses.py` | 无 | path `id` | `ExpenseItemsResponse` | Session Token | `backend/tests/test_expense_items.py` | v1.0 账单明细行；viewer 可读 |
| `/api/expenses/{id}/items` | PUT | `backend/app/routes/expenses.py` | 无 | `ExpenseItemReplaceRequest` | `ExpenseItemsResponse` | Session Token，owner/member 写权限 | `backend/tests/test_expense_items.py` | v1.0 整体替换账单明细行 |
| `/api/expenses/{id}/splits` | GET | `backend/app/routes/expenses.py` | 无 | path `id` | `ExpenseSplitsResponse` | Session Token | `backend/tests/test_expense_splits.py` | v1.0 家庭拆账；viewer 可读 |
| `/api/expenses/{id}/splits` | PUT | `backend/app/routes/expenses.py` | 无 | `ExpenseSplitReplaceRequest` | `ExpenseSplitsResponse` | Session Token，owner/member 写权限 | `backend/tests/test_expense_splits.py` | v1.0 整体替换家庭拆账并写审计 |
| `/api/expenses/{id}` | PATCH | `backend/app/routes/expenses.py` | `updateExpense(id,request)` | `ExpenseUpdateRequest` | `ExpenseDto` | Session Token, owner/member write permission | `backend/tests/test_expenses.py` | gray/internal |
| `/api/expenses/{id}/confirm` | POST | `backend/app/routes/expenses.py` | `confirmExpense(id)` | path `id` | `ExpenseDto` | Session Token, owner/member write permission | `backend/tests/test_expenses.py`, smoke | gray/internal |
| `/api/expenses/{id}/reject` | POST | `backend/app/routes/expenses.py` | `rejectExpense(id)` | path `id` | `ExpenseDto` | Session Token, owner/member write permission | `backend/tests/test_expenses.py`, smoke | gray/internal |
| `/api/expenses/{id}/ocr/retry` | POST | `backend/app/routes/expenses.py` | `retryOcr(id)` | path `id` | `ExpenseDto` | Session Token, owner/member write permission | `backend/tests/test_expenses.py` | internal/高级入口 |
| `/api/expenses/{id}/recognize-text` | POST | `backend/app/routes/expenses.py` | 无 | `RecognizeTextRequest` | `ExpenseDto` | Session Token, owner/member write permission | `backend/tests/test_expenses.py` | internal/shortcut text |
| `/api/expenses/{id}/mark-not-duplicate` | POST | `backend/app/routes/expenses.py` | `markNotDuplicate(id)` | path `id` | `ExpenseDto` | Session Token, owner/member write permission | `backend/tests/test_expenses.py` | gray/internal |
| `/api/expenses/{id}/image` | GET | `backend/app/routes/expenses.py` | `expenseImage(id)` | path `id` | streaming image | Session Token | `backend/tests/test_expenses.py`, smoke | gray/internal |
| `/api/expenses/{id}/thumbnail` | GET | `backend/app/routes/expenses.py` | `expenseThumbnail(id)` | path `id` | streaming image | Session Token | `backend/tests/test_expenses.py`, smoke | gray/internal |
| `/api/duplicates` | GET | `backend/app/routes/duplicates.py` | `duplicates()` | 无 | `List<ExpenseDto>` | Session Token | `backend/tests/test_expenses.py` | gray/internal |
| `/api/rules/categories` | GET | `backend/app/routes/rules.py` | `categoryRules()` | 无 | `List<CategoryRuleDto>` | Session Token | `backend/tests/test_expenses.py` | internal/高级入口 |
| `/api/rules/categories` | POST | `backend/app/routes/rules.py` | `createCategoryRule(request)` | `CategoryRuleRequest` | `CategoryRuleDto` | Session Token，owner/member 写权限 | `backend/tests/test_alpha3_engine.py`, `ApiDtoContractTest` | v0.7 条件规则字段 |
| `/api/rules/categories/{id}` | PATCH | `backend/app/routes/rules.py` | `updateCategoryRule(id,request)` | `CategoryRuleRequest` | `CategoryRuleDto` | Session Token，owner/member 写权限 | `backend/tests/test_alpha3_engine.py` | v0.7 条件规则字段 |
| `/api/rules/categories/{id}` | DELETE | `backend/app/routes/rules.py` | `deleteCategoryRule(id)` | path `id` | `StatusDto` | Session Token | `backend/tests/test_expenses.py`, `ApiDtoContractTest` | internal/高级入口 |
| `/api/rules/apply-pending/preview` | POST | `backend/app/routes/rules.py` | 无 | query `limit/max_scan` | `RuleApplyPendingPreviewResponse` | Session Token | `backend/tests/test_alpha3_engine.py` | dry-run；默认最多扫描 500 条可自动填充账单 |
| `/api/rules/apply-pending` | POST | `backend/app/routes/rules.py` | 无 | query `max_scan` | `RuleApplyPendingResponse` | Session Token，owner/member 写权限 | `backend/tests/test_alpha3_engine.py`, `backend/tests/test_viewer_write_guards.py` | 只改待确认账单的默认分类 |
| `/api/rules/apply-confirmed` | POST | `backend/app/routes/rules.py` | `applyConfirmedRules(request)` | `RuleApplyConfirmedRequest`；query `limit/max_scan` | `RuleApplyConfirmedResponse` | Session Token；`confirm=true` 需 owner/member 写权限 | `backend/tests/test_alpha3_engine.py`, `ExpenseRepositoryBindingTest` | dry-run 默认；确认必须带 `preview_token` |
| `/api/rules/applications` | GET | `backend/app/routes/rules.py` | `ruleApplications(limit)` | query `limit` | `RuleApplicationListResponse` | Session Token | `backend/tests/test_alpha3_engine.py`, `ExpenseRepositoryBindingTest` | 最近规则应用批次 |
| `/api/rules/applications/{public_id}/rollback` | POST | `backend/app/routes/rules.py` | `rollbackRuleApplication(publicId)` | path `public_id` | `RuleApplicationRollbackResponse` | Session Token，owner/member 写权限 | `backend/tests/test_alpha3_engine.py`, `ExpenseRepositoryBindingTest` | 回滚未被手动改过的批次变更 |
| `/api/settings/server` | GET | `backend/app/routes/settings.py` | `serverSettings()` | 无 | `ServerSettingsDto` | Session Token | `backend/tests/test_maintenance.py` | gray/internal |
| `/api/stats/monthly` | GET | `backend/app/routes/stats.py` | `monthlyStats(month,timezone)` | query `month/tag/timezone` | `MonthlyStatsDto` | Session Token | `backend/tests/test_stats_filters.py`, `backend/tests/test_tags.py`, Android domain tests | gray/internal |
| `/api/stats/lifestyle` | GET | `backend/app/routes/stats.py` | `lifestyleStats(month,timezone)` | query `month/timezone` | `LifestyleStatsDto` | Session Token | `backend/tests/test_stats_filters.py` | gray/internal |
| `/api/reports/overview` | GET | `backend/app/routes/reports.py` | v0.9 Reports | query `month/granularity/top_n/merchant_category/ranking_metric/timezone` | `ReportsOverviewResponse` | Session Token | `backend/tests/test_reports.py` | v0.9 动态趋势、商家排行、分类环比；viewer 可读 |
| `/api/reports/overview.csv` | GET | `backend/app/routes/reports.py` | v0.9 Reports Export | query 同 `/api/reports/overview` | streaming `text/csv` | Session Token | `backend/tests/test_reports.py` | v0.9 结构化报表 CSV；viewer 可读 |
| `/api/dashboard/cards` | GET | `backend/app/routes/dashboard.py` | v0.9 Dashboard Cards | query `surface=android|web` | `DashboardCardsResponse` | Session Token | `backend/tests/test_dashboard_cards.py` | v0.9 Dashboard 卡片顺序和显隐；viewer 可读 |
| `/api/dashboard/cards` | PUT | `backend/app/routes/dashboard.py` | v0.9 Dashboard Cards | query `surface=android|web`；`DashboardCardsUpdateRequest` | `DashboardCardsResponse` | Session Token，owner/member 写权限 | `backend/tests/test_dashboard_cards.py` | v0.9 保存 Dashboard 卡片顺序和显隐 |
| `/api/me/ui-preferences` | GET | `backend/app/routes/user_preferences.py` | Android/Web UI preferences | none | `UserUiPreferencesResponse` | Session Token | Android settings/theme sync | v0.10 cross-surface UI preferences |
| `/api/me/ui-preferences` | PUT | `backend/app/routes/user_preferences.py` | Android/Web UI preferences | `UserUiPreferencesUpdateRequest` | `UserUiPreferencesResponse` | Session Token, owner/member write permission | Android settings/theme sync | v0.10 cross-surface UI preferences |
| `/api/goals` | GET | `backend/app/routes/goals.py` | v0.9 Goals | query `month/include_archived/timezone` | `GoalListResponse` | Session Token | `backend/tests/test_goals.py` | v0.9 目标列表和进度；viewer 可读 |
| `/api/goals` | POST | `backend/app/routes/goals.py` | v0.9 Goals | `GoalCreateRequest`；query `timezone` | `GoalResponse` | Session Token，owner/member 写权限 | `backend/tests/test_goals.py` | v0.9 创建月度支出目标 |
| `/api/goals/{public_id}` | GET | `backend/app/routes/goals.py` | v0.9 Goals | path `public_id`；query `timezone` | `GoalResponse` | Session Token | `backend/tests/test_goals.py` | v0.9 目标详情和进度；viewer 可读 |
| `/api/goals/{public_id}` | PATCH | `backend/app/routes/goals.py` | v0.9 Goals | `GoalUpdateRequest`；query `timezone` | `GoalResponse` | Session Token，owner/member 写权限 | `backend/tests/test_goals.py` | v0.9 更新目标配置 |
| `/api/goals/{public_id}/archive` | POST | `backend/app/routes/goals.py` | v0.9 Goals | path `public_id`；query `timezone` | `GoalResponse` | Session Token，owner/member 写权限 | `backend/tests/test_goals.py` | v0.9 归档目标，不物理删除 |
| `/api/recurring/items` | GET | `backend/app/routes/recurring.py` | `recurringItems(status,includeArchived,month,timezone)` | query `status/include_archived/month/timezone` | `RecurringItemListResponseDto` | Session Token | `backend/tests/test_recurring_items.py`, `ApiDtoContractTest` | v0.6 固定支出列表 |
| `/api/recurring/from-candidate` | POST | `backend/app/routes/recurring.py` | `confirmRecurringCandidate(request,timezone)` | `RecurringCandidateConfirmRequest`；query `timezone` | `RecurringItemDto` | Session Token，owner/member 写权限 | `backend/tests/test_recurring_items.py` | 候选确认成固定支出 |
| `/api/recurring/items/{public_id}` | GET | `backend/app/routes/recurring.py` | `recurringItem(publicId,month,timezone)` | path `public_id`；query `month/timezone` | `RecurringItemDto` | Session Token | `backend/tests/test_recurring_items.py` | 固定支出详情 |
| `/api/recurring/items/{public_id}/pause` | POST | `backend/app/routes/recurring.py` | `pauseRecurringItem(publicId)` | path `public_id` | `RecurringItemDto` | Session Token，owner/member 写权限 | `backend/tests/test_recurring_items.py` | 暂停固定支出 |
| `/api/recurring/items/{public_id}/resume` | POST | `backend/app/routes/recurring.py` | `resumeRecurringItem(publicId)` | path `public_id` | `RecurringItemDto` | Session Token，owner/member 写权限 | `backend/tests/test_recurring_items.py` | 恢复固定支出 |
| `/api/recurring/items/{public_id}/archive` | POST | `backend/app/routes/recurring.py` | `archiveRecurringItem(publicId)` | path `public_id` | `RecurringItemDto` | Session Token，owner/member 写权限 | `backend/tests/test_recurring_items.py` | 归档固定支出 |
| `/api/budgets/monthly` | GET | `backend/app/routes/budgets.py` | Android / `/web` / `/owner` 预算状态 | query `month/timezone` | `BudgetMonthlyResponse` | Session Token | `backend/tests/test_budgets.py` | v0.8 月度预算 Dashboard；viewer 可读 |
| `/api/budgets/monthly/{month}` | PUT | `backend/app/routes/budgets.py` | Android / `/web` 预算配置 | `BudgetMonthlyUpdateRequest`；query `timezone` | `BudgetMonthlyResponse` | Session Token，owner/member 写权限 | `backend/tests/test_budgets.py` | v0.8 月度预算配置；预算只提示不阻断记账 |
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
  "original_currency": "CNY",
  "original_amount": "12.80",
  "spent_at": "2026-05-04T00:30:00Z",
  "merchant": "便利店",
  "category": "生活",
  "note": "上班路上"
}
```

外币账单请求体示例：

```json
{
  "original_currency": "USD",
  "original_amount": "123.45",
  "spent_at": "2026-05-04T02:00:00Z",
  "merchant": "海外咖啡",
  "category": "餐饮"
}
```

规则：

- 新客户端只传原始币种、原始金额和发生时间；后端按 `spent_at` 日期、原始币种、home currency 和汇率优先级计算并冻结 `amount_cents`。
- 客户端不得在账单创建/编辑请求里提交 `exchange_rate_to_cny`、`fx_rate` 或 home amount 计算结果。
- 旧客户端可只传 `amount_cents`；后端按当前 home currency 原始金额和 `rate=1` 兼容。
- `spent_at` 可为空；为空时后端使用确认时间。
- `source` 固定为 `手动记账`。
- 有可用汇率时直接 `confirmed`；汇率缺失时保留 `pending` 并返回 `fx_status=pending`。
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
  "original_currency": "CNY",
  "original_amount": "26.80",
  "spent_at": "2026-05-13T10:05:00Z",
  "category": "餐饮",
  "expense_time": "2026-05-13T10:05:00Z"
}
```

规则：

- `source` 仅支持 `wechat` / `alipay` / `bank_sms` / `bank_app` / `other`。
- 请求体禁止 `raw_text` 等原文类字段；校验失败返回 `invalid_request`。
- 请求体不得包含汇率字段；后端负责计算或标记 `fx_status=pending`。
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
tag: 标签，可选
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

### GET /api/expenses/tags

请求头：

```http
Authorization: Bearer <session_token>
```

返回当前账本已经使用过的标签；标签来自账单 `tags` 文本的规范化结果。

返回：

```json
{
  "items": ["AI", "真香", "必要"]
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
tag: 标签，可选
timezone: IANA 时区名，可选；Android 默认传手机系统时区，未传时使用服务端 OCR_DEFAULT_TIMEZONE
```

返回 `text/csv`，用于导出已确认账单。导出接口只返回账单数据，不提供文件目录浏览或任意文件下载。

CSV 会包含原始币种、原始金额、汇率、汇率日期和汇率来源列；旧导入文件缺少这些列时按当前 home currency 兼容。

### GET /api/exchange-rates

请求头：

```http
Authorization: Bearer <session_token>
```

查询参数：

```text
currency_code: 可选，CNY/USD/EUR/GBP/JPY/HKD/KRW
limit: 默认 90，最大 365
```

返回当前账本的手动汇率覆盖列表。`viewer` 可读。

说明：

- 这是账本内手动校正/补录接口，不是移动端记账流程依赖的外部汇率接口。
- 账单写入时，后端优先使用账本手动汇率；没有手动汇率时使用后台定时写入 `fx_rates` 的官方参考汇率；仍缺失则返回 `fx_status=pending`。
- Android / iOS / Web 客户端不得为了创建账单直接请求外部汇率 API，也不得把自己计算出的汇率提交到账单写入接口。

### PUT /api/exchange-rates/{currency_code}/{rate_date}

请求头：

```http
Authorization: Bearer <session_token>
Content-Type: application/json
```

请求体：

```json
{
  "currency_code": "USD",
  "rate_date": "2026-05-04",
  "rate_to_cny": "7.1234",
  "source": "manual"
}
```

规则：

- 汇率按当前账本、币种、日期唯一保存。
- 只允许维护非 home currency 汇率。
- `owner` / `member` 可写，`viewer` 返回 `permission_denied`。

### POST /api/imports/csv

请求头：

```http
Authorization: Bearer <session_token>
Content-Type: multipart/form-data
```

表单字段：`csv_file`。CSV 必须包含 `amount_yuan` 或 `amount_cents`，可选列包括 `merchant/category/note/expense_time/tags/source/original_currency_code/original_amount_minor/exchange_rate_to_cny/exchange_rate_date/exchange_rate_source`。接口会持久化导入批次和行级校验结果，不直接写入账单；viewer 返回 `permission_denied`。

规则：

- 单批最多 20000 个非空数据行。
- 行级错误不会阻断批次创建，错误行通过分页预览和 `errors.csv` 查看。
- CSV 的汇率列仅用于历史文件兼容和审计展示；真正写入账单时仍由后端汇率解析器按日期、币种和汇率优先级冻结 home amount。
- 服务端只保存文件名，不保存客户端路径、不返回本机路径。

### GET /api/imports/csv/{public_id}

读取导入批次状态。跨账本读取返回 `import_batch_not_found`。

### GET /api/imports/csv/{public_id}/rows

查询参数：

```text
page: 默认 1
page_size: 默认 100，最大 500
status: 可选，valid/error/applied/insert_failed
```

返回分页行，用于大 CSV 预览，不需要一次把全部行塞回客户端。

### POST /api/imports/csv/{public_id}/apply

请求体：

```json
{
  "batch_size": 500
}
```

每次只把当前批次中 `status=valid` 的行写入 `pending` 账单，并把成功行标记为 `applied`。重复调用只处理剩余 `valid` 行，已应用行不会重复插入。viewer 返回 `permission_denied`。

### GET /api/imports/csv/{public_id}/errors.csv

返回当前批次的 `error` / `insert_failed` 行，便于用户修正后重新导入。只允许读取当前账本批次。

### PATCH /api/expenses/{id}

请求头：

```http
Authorization: Bearer <session_token>
Content-Type: application/json
```

请求体：

```json
{
  "original_currency": "USD",
  "original_amount": "5.18",
  "spent_at": "2026-05-03T04:20:00Z",
  "merchant": "美团外卖",
  "category": "餐饮",
  "note": "午饭",
  "expense_time": "2026-05-03T04:20:00Z",
  "tags": "真香",
  "value_score": 5,
  "regret_score": 1
}
```

只能修改 `pending` 或 `confirmed`。如果请求包含原始币种、原始金额或发生时间，后端会按汇率优先级重新解析并冻结 home amount；客户端不得提交汇率或自行折算后的 home amount。只传 `amount_cents` 时仍按旧客户端 home currency 兼容。

### GET /api/expenses/{id}

请求头：

```http
Authorization: Bearer <session_token>
```

返回单条账单详情，响应结构同 `ExpenseResponse`。找不到返回 `expense_not_found`。

### GET /api/expenses/{id}/items

请求头：

```http
Authorization: Bearer <session_token>
```

返回指定账单的明细行。明细行是 v1.0 的独立子资源，不并入 `ExpenseResponse`，不会改变账单确认、统计、预算或导出结果。跨账本读取返回 `expense_not_found`。viewer 可读。

OCR 或 `recognize-text` 能从足够明确的小票文本中生成 `is_ocr_draft=true` 的明细行；后续 OCR 可替换旧 OCR 草稿明细，但不会覆盖用户通过 `PUT /api/expenses/{id}/items` 写入的手工明细。

返回示例：

```json
{
  "expense_id": 1,
  "parent_amount_cents": 1500,
  "items_total_amount_cents": 1250,
  "mismatch_cents": 250,
  "items": [
    {
      "public_id": "7c8b0f7a-9f44-4654-8ec9-0f91c5f3dd18",
      "position": 0,
      "name": "拿铁",
      "quantity_text": "1杯",
      "unit_price_cents": 500,
      "amount_cents": 500,
      "category": "餐饮",
      "raw_text": "拿铁 1杯 5.00",
      "confidence": 0.92,
      "is_ocr_draft": false,
      "created_at": "2026-05-03T04:20:00Z",
      "updated_at": "2026-05-03T04:20:00Z"
    }
  ]
}
```

### PUT /api/expenses/{id}/items

请求头：

```http
Authorization: Bearer <session_token>
Content-Type: application/json
```

请求体：

```json
{
  "items": [
    {
      "name": "拿铁",
      "quantity_text": "1杯",
      "unit_price_cents": 500,
      "amount_cents": 500,
      "category": "餐饮",
      "raw_text": "拿铁 1杯 5.00",
      "confidence": 0.92
    }
  ]
}
```

规则：

- 只能整体替换同一账单的明细行，最多 200 行。
- 只允许修改 `pending` 或 `confirmed` 账单；`rejected` 返回 `expense_not_found`。
- `position` 由服务端按请求顺序生成。
- `items_total_amount_cents` 只汇总带 `amount_cents` 的明细；`mismatch_cents = parent_amount_cents - items_total_amount_cents`。
- viewer 返回 `permission_denied`。

### GET /api/expenses/{id}/splits

请求头：

```http
Authorization: Bearer <session_token>
```

返回指定账单的家庭拆账行。拆账行是 v1.0 的独立子资源，不并入 `ExpenseResponse`，不会改变账单确认、统计、预算或 CSV 导出结果。跨账本读取返回 `expense_not_found`。viewer 可读。

返回示例：

```json
{
  "expense_id": 1,
  "parent_amount_cents": 10000,
  "splits_total_amount_cents": 9000,
  "mismatch_cents": 1000,
  "splits": [
    {
      "public_id": "04d3cfd1-58c8-4d9f-8f87-1a5686404202",
      "position": 0,
      "member_id": 12,
      "account_name": "我",
      "role": "owner",
      "amount_cents": 6000,
      "note": "我出大头",
      "disabled_at": null,
      "created_at": "2026-05-03T04:20:00Z",
      "updated_at": "2026-05-03T04:20:00Z"
    }
  ]
}
```

### PUT /api/expenses/{id}/splits

请求头：

```http
Authorization: Bearer <session_token>
Content-Type: application/json
```

请求体：

```json
{
  "splits": [
    {
      "member_id": 12,
      "amount_cents": 6000,
      "note": "我出大头"
    },
    {
      "member_id": 13,
      "amount_cents": 3000,
      "note": "一起吃饭"
    }
  ]
}
```

规则：

- 只能整体替换同一账单的拆账行，最多 100 行。
- `member_id` 必须是当前账本的有效成员；跨账本、缺失、已停用成员返回 `member_not_found`。
- 已有拆账行在成员停用后仍保留原成员姓名、角色和 `disabled_at`，但不能再把停用成员写入新的拆账替换请求。
- 同一个成员不能在同一账单内重复出现，重复返回 `invalid_request`。
- 只允许修改 `pending` 或 `confirmed` 账单；`rejected` 返回 `expense_not_found`。
- `position` 由服务端按请求顺序生成。
- `splits_total_amount_cents` 汇总拆账金额；`mismatch_cents = parent_amount_cents - splits_total_amount_cents`。
- 成功替换会写入成员审计日志 `expense_splits_replaced`，`detail` 包含 `expense_public_id` 以及 before/after 的成员分配摘要。
- viewer 返回 `permission_denied`。

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
- 对 `pending` 账单，如果文本中存在明确的商品行，会生成 OCR 草稿明细；已存在手工明细时不会覆盖。
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
  "priority": 5,
  "amount_min_cents": 1000,
  "amount_max_cents": 50000,
  "source_contains": "pytest",
  "tag_contains": "订阅"
}
```

`amount_min_cents`、`amount_max_cents`、`source_contains`、`tag_contains` 都是可选条件。规则必须先命中关键词，再同时满足这些条件才会改写分类。

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

### POST /api/rules/apply-confirmed

默认是 dry-run，不写数据库：

```json
{
  "confirm": false
}
```

响应包含 `preview_token`。真正写入已确认历史账单时必须带回同一个 token：

```json
{
  "confirm": true,
  "preview_token": "<dry-run 返回的 preview_token>"
}
```

如果规则、别名或候选账单在预览后发生变化，确认写入返回：

```json
{
  "error": "preview_stale",
  "message": "预览已过期，请重新预览后再确认。"
}
```

`apply-pending` 与 `apply-confirmed` 默认只扫描前 500 条仍可自动填充分类的账单，最大 1000。响应中的 `scan_limit_reached=true` 表示还有剩余候选账单，需要再次预览并应用。

### GET /api/rules/applications

返回最近规则应用批次，用于审计和回滚入口。

### POST /api/rules/applications/{public_id}/rollback

回滚指定批次中尚未被用户手动改写的账单分类。已改变到其他分类的账单会跳过。

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
tag=真香
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
  ],
  "by_tag": [
    {
      "tag": "真香",
      "amount_cents": 3680,
      "count": 2
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

## 报表

> v0.9 起提供服务端报表聚合。报表接口只返回结构化统计数据，不返回图表库私有格式，不做图片渲染。前端用它绘制 Android / `/web` 动态趋势、商家排行和分类环比。

### GET /api/reports/overview

请求头：

```http
Authorization: Bearer <session_token>
```

查询参数：

```text
month=2026-05
granularity=day|week|month，默认 day
top_n=8，范围 1..20
merchant_category=餐饮，可选；只过滤商家排行，不影响总额和分类对比
ranking_metric=amount|count，默认 amount
timezone=Asia/Shanghai
```

规则：

- 只统计当前账本的 `confirmed` 账单。
- 统计时间口径与 `/api/stats/monthly` 一致：优先 `expense_time`，为空时使用 `confirmed_at`。
- `day` / `week` 按指定 `timezone` 的本地自然日和自然周分桶；`month` 返回截至目标月的 6 个月趋势。
- 商家排行按当前月份聚合金额和笔数，并按已启用商家别名合并展示名；`merchant_category` 只过滤商家排行，`ranking_metric` 控制按金额或笔数排序。
- 分类对比返回当前月、上月和差额；旧分类别名会按分类归一规则合并。
- `viewer` 可读；接口不要求 writer 权限。

返回：

```json
{
  "month": "2026-05",
  "timezone": "Asia/Shanghai",
  "granularity": "day",
  "total_amount_cents": 4200,
  "count": 3,
  "previous_month": "2026-04",
  "previous_total_amount_cents": 500,
  "previous_count": 1,
  "merchant_category": null,
  "ranking_metric": "amount",
  "trend": [
    {
      "bucket": "2026-05-01",
      "label": "05-01",
      "amount_cents": 1200,
      "count": 1
    }
  ],
  "merchant_ranking": [
    {
      "merchant": "星巴克",
      "amount_cents": 2000,
      "count": 2
    }
  ],
  "category_comparison": [
    {
      "category": "餐饮",
      "amount_cents": 2000,
      "count": 2,
      "previous_amount_cents": 500,
      "previous_count": 1,
      "delta_amount_cents": 1500,
      "delta_count": 1
    }
  ]
}
```

### GET /api/reports/overview.csv

请求头：

```http
Authorization: Bearer <session_token>
```

查询参数同 `/api/reports/overview`。

返回 `text/csv; charset=utf-8`，带 UTF-8 BOM 和下载文件名。CSV 分四段：

- `summary`：月份、时区、粒度、总额、上月总额、商家排行过滤和排序参数。
- `trend`：趋势桶、展示标签、金额、笔数。
- `merchant_ranking`：排行名次、商家、金额、笔数。
- `category_comparison`：分类本月、上月和差额。

PNG 导出仍由 Android / `/web` 展示层完成；后端不渲染图表图片。

## Dashboard 卡片

> v0.9 起提供 Dashboard 卡片顺序和显隐配置。该接口只保存展示偏好，不改变统计、预算、Goals 或账本数据口径；Android 和 `/web` 使用独立 `surface`。

### GET /api/dashboard/cards

查询参数：

```text
surface=android|web，默认 android
```

返回：

```json
{
  "surface": "web",
  "items": [
    {
      "key": "reports",
      "title": "报表",
      "visible": true,
      "position": 0
    }
  ]
}
```

规则：

- 只读取当前账本的偏好；不接受 query 参数切换账本。
- 首次读取返回服务端默认卡片库。
- `viewer` 可读。

### PUT /api/dashboard/cards

仅 `owner` / `member` 可调用。请求：

```json
{
  "cards": [
    {"key": "goals", "visible": true, "position": 0},
    {"key": "reports", "visible": false, "position": 1}
  ]
}
```

规则：

- `key` 必须来自该 `surface` 的默认卡片库。
- 重复 `key`、未知 `key` 或非法 `surface` 返回 `invalid_request`。
- 未提交的默认卡片会保留默认显隐，并排在已保存偏好之后，便于后续新增卡片向前兼容。

## 目标

> v0.9 起提供月度支出目标。第一刀只支持 `spending_limit` + `monthly`，用于外卖、购物、总支出等“不要超过”的目标；不做储蓄目标、资产目标或自动入账。

### GET /api/goals

请求头：

```http
Authorization: Bearer <session_token>
```

查询参数：

```text
month=2026-05
include_archived=false
timezone=Asia/Shanghai
```

规则：

- 只读取当前账本目标。
- `viewer` 可读。
- 进度只统计当前账本、指定月份、`confirmed` 账单。
- 统计时间口径与 `/api/stats/monthly` 一致：优先 `expense_time`，为空时使用 `confirmed_at`。
- `category` 为空表示总支出目标；有值时只统计该分类，分类按现有归一规则处理。

返回：

```json
{
  "items": [
    {
      "public_id": "goal-uuid",
      "ledger_id": "owner",
      "name": "控制餐饮",
      "goal_type": "spending_limit",
      "period": "monthly",
      "month": "2026-05",
      "category": "餐饮",
      "target_amount_cents": 20000,
      "spent_amount_cents": 12800,
      "remaining_amount_cents": 7200,
      "progress_percent": 64,
      "progress_state": "on_track",
      "status": "active",
      "created_at": "2026-05-14T08:00:00Z",
      "updated_at": "2026-05-14T08:00:00Z",
      "archived_at": null
    }
  ]
}
```

`progress_state`：

```text
not_started  本月还没有相关支出
on_track     已有支出但未接近上限
near_limit   已达到目标金额的 80% 及以上
over_limit   已达到或超过目标金额
archived     目标已归档
```

### POST /api/goals

仅 `owner` / `member` 可调用；`viewer` 返回 `permission_denied`。

```json
{
  "name": "控制餐饮",
  "month": "2026-05",
  "category": "餐饮",
  "target_amount_cents": 20000,
  "goal_type": "spending_limit",
  "period": "monthly"
}
```

校验：

- `name` 去掉首尾空格后必须为 1..80 字。
- `month` 必须是有效 `YYYY-MM`。
- `target_amount_cents` 必须大于 0。
- 第一刀 `goal_type` 只支持 `spending_limit`，`period` 只支持 `monthly`。

### GET /api/goals/{public_id}

读取单个目标详情和当前进度。跨账本读取返回 `goal_not_found`。

### PATCH /api/goals/{public_id}

仅 `owner` / `member` 可调用。支持局部更新：

```json
{
  "name": "全月总支出",
  "category": null,
  "target_amount_cents": 50000
}
```

已归档目标不能继续修改，返回 `invalid_request`。

### POST /api/goals/{public_id}/archive

仅 `owner` / `member` 可调用。归档目标，不物理删除历史配置；默认列表不会返回归档目标，除非 `include_archived=true`。

## 预算

> v0.8 起提供服务端账本预算基线。预算只生成提示和 Dashboard 数据，不阻断上传、手动记账、确认或规则应用。

### GET /api/budgets/monthly

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
  "ledger_id": "owner",
  "month": "2026-05",
  "configured": true,
  "total_amount_cents": 100000,
  "rollover_amount_cents": 5000,
  "fixed_amount_cents": 6800,
  "non_monthly_amount_cents": 15000,
  "flex_budget_cents": 83200,
  "spent_amount_cents": 15500,
  "excluded_amount_cents": 9900,
  "remaining_amount_cents": 89500,
  "overspent_amount_cents": 0,
  "excluded_categories": ["医疗"],
  "excluded_breakdown": [
    {
      "category": "医疗",
      "amount_cents": 9900,
      "count": 1
    }
  ],
  "category_budgets": [
    {
      "category": "餐饮",
      "amount_cents": 10000,
      "spent_amount_cents": 12000,
      "remaining_amount_cents": -2000,
      "overspent_amount_cents": 2000
    }
  ],
  "updated_at": "2026-05-14T08:00:00Z"
}
```

口径：

- `fixed_amount_cents` 来自当前账本 active/monthly 固定支出的 `baseline_amount_cents`。
- `spent_amount_cents` 只统计当前账本、指定月份、confirmed 账单，时间口径与 `/api/stats/monthly` 一致：优先 `expense_time`，为空时使用 `confirmed_at`。
- `excluded_categories` 对应分类的 confirmed 金额进入 `excluded_amount_cents` / `excluded_breakdown`，不计入顶层 `spent_amount_cents`。
- `remaining_amount_cents = total_amount_cents + rollover_amount_cents - spent_amount_cents`。
- `flex_budget_cents = max(total_amount_cents + rollover_amount_cents - fixed_amount_cents - non_monthly_amount_cents, 0)`。

### PUT /api/budgets/monthly/{month}

仅 `owner` / `member` 可调用；`viewer` 返回 `permission_denied`。同一账本同一月份重复调用会更新既有记录，并以本次请求的 `category_budgets` 替换该月分类预算。

```json
{
  "total_amount_cents": 100000,
  "non_monthly_amount_cents": 15000,
  "rollover_amount_cents": 5000,
  "excluded_categories": ["医疗"],
  "category_budgets": [
    {
      "category": "餐饮",
      "amount_cents": 10000
    },
    {
      "category": "交通",
      "amount_cents": 5000
    }
  ]
}
```

校验：

- `month` 必须是 `YYYY-MM` 且月份有效。
- 金额字段使用分，`total_amount_cents`、`non_monthly_amount_cents`、分类预算金额不能为负；`rollover_amount_cents` 允许为负，用于表达上月超支带入。
- 分类会按现有分类归一规则处理；归一后重复的分类预算返回 `invalid_request`。

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
