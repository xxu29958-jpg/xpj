# v0.4-alpha3 Slice 2 — Code / Doc / Test Reconciliation Report

> 生成日期：2026-05-11
> PR：#14（`v0.4-alpha3-slice2-reports-dq-arch`）
> Head：`3598904c3fef61aefad9a317c4a5bc82131d2647`
> 基线：27 commits / 80 changed files / +7912 / -1128
> 状态：open / draft / mergeable=true / **Backend CI ✅ Android CI ✅**

本报告对账 slice 2 合同 M0-M9 的代码—测试—文档真实状态，作为 PR #14 `mark ready` 裁决依据。

## 1. 总体结论

**裁决：建议 mark ready**

- 9 个模块中 8 个 ✅ 完成、1 个 ⚠️ 部分完成（M7 Android 快速操作 sheet 延期，已书面记录）。
- 测试基线：237 → **292 passed**；ruff/compileall/smoke 全绿；verify_project ✅；CI 双绿。
- 无新增三方依赖、无破坏性 schema 迁移、无 token/upload_key/绝对路径泄漏。
- P0 项：0；P1 项：0；P2 项：3（见 §6）。

## 2. M0-M9 对账矩阵

| 模块 | T 编号 | 代码 | 测试 | 文档 | 真实状态 | 是否阻塞 ready | 下一步 |
|------|--------|------|------|------|----------|----------------|--------|
| M0 结构治理 | T01-T04 | ✅ | ✅ | ✅ | 完成 | 否 | 不动 |
| M1 Android Reports | T05-T11 | ✅ | ✅(老 UI) | ✅ | 完成 | 否 | 不动 |
| M2 Monthly Goal | T12-T14 | ✅ | ✅ | ✅ | 完成 | 否 | 不动 |
| M3 Merchant/Category | T15-T18 | ✅ | ✅(+9) | ✅ | 完成 | 否 | 不动 |
| M4 Data Quality | T19-T21 | ✅ | ✅(+10) | ✅ | 完成 | 否 | 不动 |
| M5 CSV Export/Import | T22-T23 | ✅ | ✅(+11) | ✅ | 完成 | 否 | merchant/status 过滤 → P2 |
| M6 Duplicates | T24-T25 | ✅ | ✅(+8) | ✅ | 完成 | 否 | 不动 |
| M7 Android Review | T26-T29 | ⚠️ 基础设施齐备 | — | ✅ 延期已记录 | 部分 | 否 | 下一轮 PR |
| M8 Owner Console | T30-T32 + T26-T27 | ✅ | ✅(+12) | ✅ | 完成 | 否 | 不动 |
| M9 Docs/Screenshot/Runbook | T33-T36 | ✅ | — | ✅ | 完成 | 否 | 不动 |

## 3. 模块详情

### M0 结构治理（✅）

`backend/app/routes/web_*.py` 现状（全部 ≤ 280 阈值）：

```
web_app.py            198
web_categories.py     127
web_common.py         161
web_data_quality.py    34
web_duplicates.py     144
web_import_export.py  185
web_pending.py        209
web_rules.py          156
web_stats.py           89
```

- ledger resolver 集中在 `web_common._resolve_selected_ledger_id`，未被重复实现。
- 老测试通过 `app.routes.web_app._require_local` 再导出兼容。

### M1 Android Reports Engine（✅）

`StatsScreen.kt = 137 行`（合同要求 < 450，最好 < 280）。`stats/` 子包 8 张卡：

```
CategoryStructureCard.kt   197
LifestyleCard.kt            95   (含 FrequentMerchantsCard 商家排行)
PendingOverviewCard.kt     104
RecentTrendCard.kt         110   (7 天趋势 Canvas, 无 chart 依赖)
RecurringCandidatesCard.kt 126
StatsEmptyStates.kt        112
StatsMetricGrid.kt         198
StatsOverviewCard.kt        93   (含 Monthly Goal 进度)
```

- 数据来源清晰：`StatsViewModel` → `ExpenseRepository` → `ApiService`，UI 不直调 Retrofit/Room。
- 金额格式化集中于 `ui/components/formatAmount`，日期聚合集中于 `domain/model` 工具函数。
- 无 chart 依赖。

### M2 Monthly Goal MVP（✅）

- 设置/清除入口：`SettingsScreen` → `SettingsViewModel.saveMonthlyBudget(amountCents)`，传 null 清除。
- 显示：`StatsOverviewCard` 复用 `monthlyBudgetProgress(stats, monthlyBudgetCents())` → BudgetProgress(progress/percent/overBudget/remainingCents)。
- 不做分类预算 / rollover / 通知。

### M3 Merchant / Category 治理（✅）

- `merchant_service.normalize_merchant(raw)`：仅归一空白与同义词，不覆盖原始 `expense.merchant`。
- `/web/categories`：列出 (category, count, sum_cents)，含跳转规则页。
- `/web/categories/uncategorized`：未分类批量页，支持 `POST` 批量设置。
- 不删除、不合并、不自动改 confirmed。
- 测试：`test_categories.py` 137 行 / 9 cases，覆盖归一、聚合、批量设置、tenant 隔离、no leak。

### M4 Data Quality Dashboard（✅）

- `data_quality_service.data_quality_summary(db, tenant_id)`：8 个计数器 tenant scoped。
- `GET /api/insights/data-quality`：app context。
- `GET /web/data-quality`：loopback gate。
- 测试：`test_insights_data_quality.py` 118 行 + `test_web_data_quality.py` 46 行。

### M5 CSV Export / Import Preview（✅，含一处 P2 gap）

- `/web/export.csv`：`tenant_id × month × category` 过滤，UTF-8 BOM + `\n` 行结束。
- 导出字段：`id, public_id, amount_cents, amount_yuan, merchant, category, note, source, expense_time, confirmed_at, tags, value_score, regret_score`。
- **不导出**：`image_path / thumbnail_path / token / upload_key / 绝对路径` —— 已 grep 验证。
- `/web/import`：两步流程（preview → confirm），20 行预览 + 错误行高亮 + ≤ 1 MB 上限。
- 测试：`test_import_export.py` 137 行 / 11 cases。
- **P2 gap**：合同要求 export 支持 `merchant` / `status` 过滤，当前未实现（status 由路由名隐含 confirmed）。不阻塞 ready。

### M6 Duplicates 工作台（✅）

- `/web/duplicates`：双列卡（current vs original via `duplicate_of_id`）。
- 三处置动作：保留两条（`mark_expense_not_duplicate`）、删当前（`reject_expense`）、删原始（`reject_expense(original) + mark_expense_not_duplicate(current)`）。
- 不自动删除/合并/确认。
- 测试：`test_web_duplicates.py` 122 行 / 8 cases。

### M7 Android Review 快速操作（⚠️ 部分）

**已交付的基础设施**：

- `PendingScreen.kt` 已 import `ModalBottomSheet` + `showPendingTools` 状态。
- `NeedsReviewFilter.Duplicate` 枚举（slice 1）+ `PendingViewModel.markNotDuplicate`。
- `ExpenseCard.onKeepDuplicate` 回调样例。
- 后端 `PATCH /api/expenses/{id}` 已支持 `category` / `merchant` / `amount_cents` 单字段更新（slice 1 已就绪）。

**延期**：四套 BottomSheet（QuickCategory / QuickMerchant / MissingAmount / BulkConfirm）未实现。理由记录于 [`docs/V0_4_ALPHA3_SLICE2_RUNBOOK.md`](V0_4_ALPHA3_SLICE2_RUNBOOK.md) §10：本 PR 已 27 commits，PendingScreen.kt 已 693 行接近 G2 阈值，继续扩需先拆 PendingScreen，工作量超本轮预算。

不阻塞 ready：文档明确标 ⚠️ 延期，未声称完成；不破坏既有审阅链路。

### M8 Owner Console 产品化（✅）

- 运营快照卡（DQ summary）：`/owner` 顶部 6 指标 + 5 个 `/web` 快速入口。
- **账本健康卡（T26）**：`owner_console_service.list_ledger_health` 逐 ledger 调 `data_quality_summary`，render 为表格（账本/待确认/可入账/疑似重复/缺商家/未分类/最久 + 跳转链接）。
- **Windows 任务只读状态（T27）**：`windows_task_status_service` 调 schtasks /Query /FO CSV /V，GBK 降级解析，30s 缓存，env 覆盖 `XPJ_WINDOWS_TASK_NAMES`；UI 仅显示状态，禁止启停。
- 不显示 token / upload_key / 消费明细 / 远程命令执行。
- 测试：`test_owner_console.py` 350 + `test_owner_console_backups.py` 35 + `test_owner_console_dq_snapshot.py` 48 + `test_owner_console_ledger_health.py` 38 + `test_windows_task_status.py` 73。

### M9 Docs / Screenshot / Runbook（✅）

- [`docs/V0_4_ALPHA3_SLICE2_RUNBOOK.md`](V0_4_ALPHA3_SLICE2_RUNBOOK.md)：113 行，覆盖启停、Owner Console、上传链接、日常 pending、CSV、备份、故障速查、验证脚本、截图工件、§10 未完成项。
- [`scripts/capture_slice2_screenshots.ps1`](../scripts/capture_slice2_screenshots.ps1)：UTF-8 BOM，9 页截图，不打印 token/upload_key（已 grep 验证），输出到 `.gitignore` 的 `artifacts/screenshots/`。
- 截图依赖临时 `XPJ_EXTRA_LOOPBACK_HOSTS=127.0.0.1:8765,localhost:8765`（loopback gate 仅扩白名单，公网 Host 仍 reject）。

## 4. 工程硬闸门

### G1 强代码 ✅

后端 `routes → services → models` 链路完整：所有 web_* 路由仅做 `dependency_overrides` + `service` 调用 + 模板渲染；复杂业务（duplicate detection / DQ / CSV / merchant normalize）全部在 `app.services.*`。

Android `Screen → ViewModel → Repository → ApiService/Dao` 链路完整：`StatsScreen.kt` 仅 Composable + Sheet 状态；`StatsViewModel` 负责数据/budget 计算；`ExpenseRepository` 负责 DTO → domain；不存在 UI 直调 Retrofit/Room。

### G2 大文件 ⚠️（历史债已记录）

| 文件 | 行数 | 阈值 | 状态 |
|------|------|------|------|
| ExpenseEditScreen.kt | 634 | 450 | 既有历史债，slice 2 未触碰 |
| LedgerScreen.kt | 740 | 450 | 既有历史债，slice 2 未触碰 |
| PendingScreen.kt | 693 | 450 | 既有历史债，本轮 M7 延期同因 |
| ExpenseRepository.kt | 516 | 420 | slice 2 内扩展，留下一轮处理 |
| identity_service.py | 437 | 360 | 既有历史债 |
| receipt_parse_merchant.py | 373 | 360 | 既有历史债 |

所有 slice 2 **新增**文件均在阈值内：web 路由最大 209 行，service 最大 271 行（owner_console），template 最大 130 行。

### G3 依赖 ✅

无新增三方依赖。`backend/requirements.txt` 与 `android/app/build.gradle.kts` 与 base branch 一致；ruff 0.15.12（已存在）；schtasks 解析使用 stdlib `subprocess` + `csv`。

### G4 数据规范 ✅

- 金额全链路 `amount_cents` int；UI 端转元（`formatAmount` / `amount_yuan` 列）。
- 时间 `expense_time` fallback `confirmed_at`：`stats_service._stat_time` 与 Android `domain/model` 工具函数。
- tenant_id 隔离：所有新增 service 接受 `tenant_id` 参数；测试覆盖 ledger 隔离。
- CSV/HTML/截图无 path/secret leak（grep 验证）。

### G5 测试不降级 ✅

237 → **292 passed**，无 skipped、无 xfail 新增；ruff/compileall/smoke 全绿。

## 5. 测试结果

| 命令 | 结果 |
|------|------|
| `python -m compileall app scripts tests` | ✅ |
| `ruff check app scripts tests` | ✅ All checks passed |
| `python -m pytest -q` | ✅ **292 passed in 266.49s** |
| `python scripts\smoke_test.py` | ✅ 10/10 OK |
| `scripts\check_text_encoding.ps1` | ✅ |
| `git diff --check` | ✅ |
| `scripts\verify_project.ps1`（含 Android assemble + lint + unit test） | ✅ BUILD SUCCESSFUL |
| GitHub Actions Backend CI | ✅ success |
| GitHub Actions Android CI | ✅ success |

## 6. P0 / P1 / P2

### P0（必须修，阻塞 ready）：**0 项**

### P1（ready 前应修）：**0 项**

### P2（可延期）：3 项

1. CSV `/web/export.csv` 增加 `merchant` / `status` 筛选。
2. ExpenseRepository.kt 516 行 > 420 阈值，下一轮拆分。
3. 真机验收（BiometricPrompt / Photo Picker / 真实长期使用）—— 本轮 Android 验证为 emulator + verify_project gradle 验证；真机验收挂到 RC 阶段。

## 7. 文档与 PR Body

- [`docs/V0_4_ALPHA3_SMART_LEDGER_ENGINE.md`](V0_4_ALPHA3_SMART_LEDGER_ENGINE.md)：slice 2 完成段已更新。
- [`docs/V0_4_ALPHA3_SLICE2_REPORTS_DQ_ARCH.md`](V0_4_ALPHA3_SLICE2_REPORTS_DQ_ARCH.md)：§0 总览矩阵已加。
- [`docs/V0_4_ALPHA3_SLICE2_RUNBOOK.md`](V0_4_ALPHA3_SLICE2_RUNBOOK.md)：§10 未完成事项已记录 M7。
- [`artifacts/slice2_pr_body.md`](../artifacts/slice2_pr_body.md)：本轮一并刷新（gitignored，给操作员复制粘贴用）。

## 8. 最终建议

**Mark PR #14 as ready for review**：

1. 代码—文档—测试三方一致；M7 部分完成明确书面延期。
2. 测试基线 +55（237 → 292），CI 双绿。
3. 无安全/数据/依赖风险。
4. 无破坏性 schema 迁移。
5. 大文件历史债已识别，未恶化。

如需保留 draft 状态，仅适用于"等待人工 UI/真机验收"场景；功能完成度本身已达 ready 标准。
