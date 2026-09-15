# B04 原期次「记录本期付款」（AUDIT_BASE `c34efb40`）

扫描：TRACED
当前能力：Android 已知币种路径 PRESERVED（#412/#414）；Web 系列预填 MISSING；未知币种选择见 B02
修复：PROPOSED（Web `/web/expenses/new` 从原 series 预填商家/币种/金额；未知币种见 B02）
证据等级：源码 + 现有 JVM（离线录入、空流水文案）。未跑实机空流水。

## Android

入口：`RecurringOccurrenceSheet` L75–82 `occurrence-record-payment` → `RecurringPeriodPaymentSession.recordPeriodPayment` L52–75。
约束：`canWrite` 且 `occurrence.state == "unfulfilled"`。

- 空已确认流水：`OccurrencePaymentPicker` L149 `occurrence_no_payments`；记录付款不依赖已有流水。
- 建议：`RecurringOccurrenceHost` initials L71–76 商家/分类/备注/金额来自 origin；币种 `initialCurrency = paymentCurrency`。
- 可编辑实际时间：`LedgerManualExpenseSheet.kt` L100 `expenseTime = nowUtcIso()`，日期/时间选择器 L108–177 写入 draft `expenseTime` L193。
- 已加载后离线：`RecurringOccurrenceViewModelTest`（约 L350–389）在 fetch/sync 失败后仍能 `recordPeriodPayment` 并 `createManualExpense`，不增网络计数。

未知币种时 Host 不打开 sheet（B02）。

## Web

入口：`web_recurring_occurrences.py` `_page` L74–82 `flow_href("/web/expenses/new", return_to=recurring_occurrence, series, return_month=occurrence.period)`。
GET `web_manual_expense_new` L210–238：**不读 series**，`values` 默认空；`spent_at` 默认当前会计时区（`_manual_expense_context` L104–107）。
用户必须手填商家/币种/金额。`spent_at` 可编辑。空付款列表由 `payments` 渲染（`recurring_occurrence.html`）。

## 排除解释

不是第二套付款 writer。Android 走既有 `ManualExpenseSheet` / `createManualExpense`。Web 走既有 `/web/expenses/new`。
