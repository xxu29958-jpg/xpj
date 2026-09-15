# TBX-404-405-RECONCILE 交接入口

状态：`INCOMPLETE`（f1068d12 审查所列 P1/P2 已在工作树返修；不是 #404/#405 全范围完成，不要合并）
任务：完整核对 #404/#405 及后续承接。允许结束态仍是 INCOMPLETE / SCAN_COMPLETE_*。

## SHA

- 仓库：`xxu29958-jpg/xpj`
- 分支：`cursor/tbx-404-405-reconcile-20260915`
- REVIEW_TIP：`f1068d12a435b0545fe66702bd57e36de49170e4`（交接文档提交；独立审查对象之一）
- PRODUCTION_CODE_HEAD：`2e11d1c2c93641abdfa90593817c946f0b2d7895`（已推送生产代码；审查时生产停在此 SHA）
- 返修输入：`3d41f8f4afcdba89bd68b1f7dbb885e9b5ba063b`
- 对照 main：`c34efb40b89c4fecd85478888ed68ce84a90f10f`
- #405 对照（非金标准）：`c0279d865dca15bb1ac1786d66c1119ed0448db6`
- #415（仅 B01 币种入口）：`14c9eca8cf6a301a6f0d9c7a7c8dfb0227c424b9`
- #404 merge：`a6ebf182a753b5c0ea881a3913a39459a3e10041`

施工面：本仓库工作树（REVIEW_TIP + 未提交 P1/P2 返修）
扫描卡：`docs/current/tbx-404-405-reconcile/evidence/`
文件归属：`docs/current/tbx-404-405-reconcile/inventory/file-attribution.tsv`（UNMAPPED=0）。

未 merge、未装日用、未改用户数据、未调用 Codex。

## 不要整体回退的已确认正向改动（3d41f8f4）

| 能力 | 入口 | 不要回退的原因 |
|---|---|---|
| B01 两端外币创建 | Android `RecurringEditor` `selectCurrency`；Web `#rc-add-currency` | 已有 JVM/Web GET→POST→DB 证据 |
| B07 bindExact | `createManualExpense(draft, submitted.binding)` → `bindExact` | 只修期次付款入队接缝 |
| B05 Web 草稿来源 | `manual-drafts.js` `return_*` + `draftHref()` | 原 JS blob 四项保留 |
| B10 返回焦点 | `return_payment_expense_id` → `payment_id`；`preferredPaymentClientRef` | 焦点卡存在；本轮补了核对回程 |

## f1068d12 审查阻断 → 工作树入口

| ID | 生产入口 | 直接反例 |
|---|---|---|
| P1 pending-FX 认回 | `reuseAdmittedLocalCreate`：Done receipt → `findByServerId`；活跃命令 → `findByClientRef` | `exact-binding create reuses a done pending-fx original instead of enqueueing again` |
| P1 未知币种金额 | `choosePeriodPaymentCurrency` 清空 planned/captured | VM 扩展原测；Compose `unknownObligationCurrencyChoiceLeavesAmountBlankUntilUserEntersIt`（已写未跑） |
| P2 session 退休 | `sessionForSeries` 只返未接纳；link 成功 `retireCompleted`；SavedStateHandle 消费 return clientRef | `completedLinkRetiresSessionAndRestoreUsesTheReturnedClientRef`：重建 VM 无显式 ref 回到八月；link 后 `open` 走 current |
| P2 Web 未知币种 | `_recurring_commitment_values` + 空选项；422 重绘补 `currency_unspecified` | `test_unknown_recurring_currency_requires_explicit_choice_then_posts_pending` |
| P2 U06 生产者 | Sheet dispose/submit `snapshotPeriodPaymentInputs`；空商家不回填 | `snapshotKeepsClearedMerchantAndRawAmountText` |
| P2 Undo/retry 出口 | invalid token 走 recurring return；retry 含 `payment_id` | `test_web_undo_invalid_token_from_recurring_returns_to_the_original_period`；invalid action 二次 retry 仍含 `payment_id` |
| U07 | 本目录 evidence/inventory/coverage 完整键 | PARTIAL：可复核索引在仓内；不是全仓重扫 |

## 仍阻塞 / 未宣称完成

- A09 Web：仍 online-first；禁止第二套 Outbox。
- C01：未从两端真实 UI 贯穿新增 JPY/USD。Compose connected 未执行。
- C03：日用安装禁止访问。
- C04：Gmail 三份最终合同无本会话入口。
- exact-tip GitHub Actions：无。窄门不是全仓资格。

## 本轮实际执行

- Android JVM：`:app:testGrayDebugUnitTest --tests RecurringOccurrencePaymentPickerTest --tests RecurringPeriodPaymentSurfaceTest --tests RecurringOccurrenceViewModelTest --tests ExpenseManualCreateOfflineTest` → **BUILD SUCCESSFUL**
- Web：`pytest tests/test_web_period_payment_fx_link_journey.py tests/test_web_expense_undo.py::test_web_undo_invalid_token_from_recurring_returns_to_the_original_period tests/test_web_expense_undo.py::test_web_reject_from_recurring_occurrence_returns_to_the_original_period tests/test_web_recurring_occurrences.py::test_web_association_invalid_action_keeps_the_original_key` → **6 passed**
- 未执行：Compose instrumentation、完整 Android 应用、PostgreSQL 全集成、日用、GitHub Actions、Codex、merge。

## 唯一下一步

独立审查工作树相对 REVIEW_TIP 的 diff。不 merge。不装日用。
