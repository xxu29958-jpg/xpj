# v0.4-alpha3 — 数据能力盘点

> 目标：在动工前盘清现有后端 / Android 数据能力，明确**本轮新增什么、不新增什么、复用什么**，避免重复造接口。
> 基线：`7bdf1a1`（v0.4-alpha2 head）。

---

## 1. 后端 Expense 字段（`backend/app/models.py:108-138`）

| 字段 | 类型 | 备注 |
|---|---|---|
| `tenant_id` | `String(64)` | 多账本隔离键 |
| `public_id` | `String(36)` | UUID |
| `amount_cents` | `Integer NULL` | 金额（分） |
| `merchant` | `String(255) NULL` | 商家原文 |
| `category` | `String(64) NOT NULL default "其他"` | **字符串，非 FK** |
| `note` | `Text` | 备注 |
| `source` | `String(64) default "iPhone截图"` | 来源 |
| `image_path` / `thumbnail_path` | `String(500) NULL` | 文件路径 |
| `image_hash` | `String(128) NULL, indexed` | 去重哈希 |
| `raw_text` | `Text` | OCR 原文 |
| `duplicate_status` | `String(32) default "none"` | `none/suspect/confirmed` |
| `duplicate_of_id` | `Integer NULL` | 疑似重复指向 |
| `tags` | `Text NULL` | 标签 |
| `value_score` / `regret_score` | `Integer NULL` | 价值评分 |
| `status` | `String(32) default "pending"` | `pending/confirmed/rejected` |
| `expense_time` | `DateTime NULL, indexed` | 消费时间 |
| `confirmed_at` / `rejected_at` | `DateTime NULL` | |

复合索引覆盖：`(tenant_id, status, created_at)`、`(tenant_id, status, expense_time)`、`(tenant_id, status, category, expense_time)`、`(tenant_id, status, amount_cents, merchant)`。

**结论**：聚合查询 by_category / by_merchant / monthly / daily 全部有索引支持。**无需建新表**。

## 2. 已有 Stats 接口

| 端点 | 实现 | 返回 |
|---|---|---|
| `GET /api/stats/monthly?month=YYYY-MM` | `stats_service.monthly_stats` | `{month, total_amount_cents, count, by_category:[{category, amount_cents, count}]}` |
| `GET /api/stats/lifestyle?month=YYYY-MM` | `stats_service.lifestyle_stats` | `{month, ai_subscription_amount_cents, digital_amount_cents, max_expense, recent_7_days_amount_cents, frequent_merchants:[{merchant, count}]}` |

**结论**：
- 分类排行 → 直接复用 `monthly.by_category`（**T04 无需新接口**）
- 7 天累计 → 复用 `lifestyle.recent_7_days_amount_cents`，但**缺每日分桶** → T06 需要新增 `daily_trend`（在 `lifestyle_stats` 内扩展或新增 `/api/stats/daily-trend`）
- 最大一笔 → 复用 `lifestyle.max_expense`（**T07 无需新接口**）
- 商家排行 → `lifestyle.frequent_merchants` 只统计 **count**，缺 `amount_cents`。**T05 需扩展或 Android 端本地算**

## 3. 已有 CategoryRule（`backend/app/models.py:164-173` + `routes/rules.py`）

| 字段 | |
|---|---|
| `tenant_id` | 已隔离 |
| `keyword` | 子串匹配源 |
| `category` | 目标分类 |
| `enabled` | 启用开关 |
| `priority` | 数值越小越优先 |

已有端点：
- `GET /api/rules/categories` 列表
- `POST /api/rules/categories` 新增
- `PATCH /api/rules/categories/{id}` 更新
- `DELETE /api/rules/categories/{id}` 删除

`classify_service.classify_expense` 在 `merchant + raw_text + note` 中做 lower-case substring 匹配，优先级低者优先；只在 `expense.category == "其他"` 时改写（`expense_service` 内多处调用）。

**结论**：
- 规则结构已足够支撑 alpha3。**T16 不需要 schema 扩展**
- T17 Rules Preview：复用 `classify_expense` 的匹配逻辑（拆出一个 `match_pending` helper），**新增端点 `POST /api/rules/preview`**
- T18 Rules Apply Pending：批量执行 `classify_expense` over pending，**新增端点 `POST /api/rules/apply-pending`**
- T19 /web rules：HTML 页面，复用现有 CRUD 端点
- 不新增 merchant 字段、不新增 merchant alias 表（T21 商家归一化 MVP 复用规则机制：keyword="STARBUCKS" target="星巴克" 用同一套 CategoryRule 替代或新增极小 `MerchantAlias` 模块——倾向**用 normalize 函数 + 现有 rule keyword 表达**，避免 schema 改动）

## 4. 已有 Settings

- 后端：`backend/app/routes/settings.py` 仅 `/api/settings/server` 返回 ledger/account 上下文，**没有 monthly budget 存储**
- Android：`LocalSettingsStore` + `ExpenseRepository.monthlyBudgetCents()` / `saveMonthlyBudgetCents(Long?)`，**本地存储**

**结论**：
- T27/T28/T29 — Android 本月目标设置：**直接复用** Android 本地存储，**无需后端字段**。本期视为"客户端配置"
- T30 /web 本月目标卡：如要做同步，需要新增 `Settings` 后端表 + endpoint，或暂以"/web 仅显示提示"（Stretch）。本 PR 推荐方案：**Android 与 /web 独立，/web 第一版只读提示"请在手机端设置目标"**，避免 schema 改动

## 5. 已有 Expense Service 签名（`backend/app/services/expense_service.py`）

- `list_pending(db, tenant_id) -> list[Expense]`
- `list_confirmed(db, *, tenant_id, page, page_size, month, category, timezone_name) -> tuple[list, int]`
- `get_expense(db, expense_id, tenant_id) -> Expense`
- `update_expense(db, expense_id, tenant_id, payload) -> Expense`
- `confirm_expense(db, expense_id, tenant_id) -> Expense`（amount_cents 必须非空，否则 422）
- `reject_expense(db, expense_id, tenant_id) -> Expense`
- 自动分类：`update_expense` 在未显式设置 `category` 且当前为"其他"且改了 merchant/note 时自动调用 `classify_expense`

**结论**：T11/T12/T13/T14 批量操作全部复用单条 service 逐条调用，**禁止绕过 `confirm_expense` 的 amount 检查**。

## 6. Android Room（`android/app/src/main/java/com/ticketbox/data/local/`）

`ExpenseEntity` 与服务端字段一一对齐，含 `ledgerId`/`status`/`amountCents`/`merchant`/`category`/`expenseTime`/`confirmedAt`/`duplicateStatus`。

`ExpenseDao` 已有：
- `observeConfirmed(ledgerId)` Flow
- `getConfirmed(ledgerId)`
- `upsertByServerIdForLedger`
- `clearForLedger`
- `findAnyByServerIds`（**禁止触碰**，alpha1 安全契约）

**结论**：
- T05 商家排行本地计算 → 可新增 DAO 聚合查询（`SELECT merchant, SUM(amountCents), COUNT(*) ... GROUP BY merchant`），**不改 schema**
- T06 7 天趋势本地计算 → 可在 DAO 加日期范围 query 或 Repository 层 groupBy

## 7. Android Repository / ViewModel

- `ExpenseRepository.monthlyBudgetCents() / saveMonthlyBudgetCents(Long?)` 已存在 → T28/T29 直接复用
- `StatsViewModel` 暴露 `StatsUiState { monthlyStats, lifestyleStats, ... }` → T03 在此扩充 Reports cards

## 8. 本轮**不新增**的接口

- 不新增 Recurring 表 / Recurring CRUD（仅 GET 候选）
- 不新增 Budget 表
- 不新增 MerchantAlias 表（第一版用 `normalize_merchant` 函数 + 现有 rule keyword）
- 不新增 Category 表
- 不新增 DuplicateIgnore 操作端点（已有表，T15 复用既有 service）

## 9. 本轮**新增**的接口（合同）

| 端点 | 范围 | 测试 |
|---|---|---|
| `POST /api/rules/preview` | 仅预览，不改库 | preview_does_not_modify |
| `POST /api/rules/apply-pending` | 只改 pending，不自动确认 | apply_does_not_touch_confirmed / does_not_auto_confirm |
| `GET /api/insights/recurring-candidates` | 只读，按月聚合归一商家 | empty / detects_monthly / ignores_one_off |
| `POST /web/review/bulk` | /web 本机批量操作（set_category / set_merchant / reject / confirm_ready / keep_duplicate） | bulk_keeps_ledger / cross_ledger_rejected / confirm_skips_missing_amount |
| `GET /web/pending?ledger_id&filter=` | 现有路由扩展 filter query | pending_filter_missing_amount |
| 可选 `GET /api/stats/daily-trend?month=` | 7 天 / 30 天日桶 | daily_trend_groups_by_day |

## 10. 已确认可直接回答的能力问题

| 问题 | 答案 |
|---|---|
| 商家排行能算吗？ | 后端只算 count（lifestyle.frequent_merchants），缺 amount。需扩展或 Android 本地算 |
| 7 天趋势能算吗？ | 总额能（recent_7_days_amount_cents），按日分桶**不能**。本轮新增 daily_trend |
| 分类规则已有多少？ | 36 条默认（`classify_service.DEFAULT_RULES`） |
| 月度目标已有 settings 入口？ | Android 本地有 monthlyBudgetCents()/save。后端没有 |
| Recurring candidates 需新增吗？ | 后端新增 `/api/insights/recurring-candidates`（只读聚合）|
| 商家归一化要新表吗？ | 不要。本轮用 `normalize_merchant` 函数 + 现有 CategoryRule keyword 表达 |
| Duplicate ignore 表存在吗？ | 是，`DuplicateIgnore`（`models.py:181`），有 service 支持 |

---

**结论**：alpha3 的"智能"全部建立在**现有 schema** + **现有 service** + **少量新只读端点** + **/web 批量 endpoint** 之上。不会发生破坏性数据库迁移。
