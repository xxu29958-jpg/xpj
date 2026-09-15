# B02 新建可选 vs 历史单位 vs 未知币种（AUDIT_BASE `c34efb40`）

扫描：TRACED
当前能力：部分 PRESERVED，未知币种选择入口 MISSING
修复：PROPOSED（未知义务币种时打开选择，而不是关掉整张付款表）
证据等级：固定 SHA 源码 + 现有 JVM 反例。未跑未知币种实机。

## 链

1. 新建计划币种
   - `newRecurringEditorSession` `RecurringEditorSession.kt` L115–119：无 baseline 时用显示账本币种；无 `selectCurrency`（见 B01）。
2. 已有记录单位
   - 同上 L119：编辑用 `baseline.homeCurrencyCode`，不跟显示币种走。
   - `applyRebase` L73–74：rebase 币种与会话币种不一致则拒绝，不静默改写。
   - `RecurringEditorRestorationTest.recordedJpyAndRawInputSurviveRestorationUnderAnotherDefault`：JPY 记录在 USD 显示环境下仍恢复 JPY。
3. 未知币种表单
   - `RecurringEditorForm.kt` `RecurringEditorAmountField` L139–148：`currency == null` 时金额只读，文案 `recurring_amount_currency_unknown`，**没有**用户可达的币种选择。
4. 观察候选
   - `recurring.html` review/candidate 展示 `home_currency_code` 只读；采用建议不改写历史观察单位。
5. 付款入口未知义务币种
   - `RecurringPeriodPaymentSession.recordPeriodPayment` L69：`obligationCurrencyCode = occurrence.homeCurrencyCode`（可为 null）。
   - `RecurringOccurrenceViewModelTest.unknownObligationCurrencyDoesNotGuessLedgerHomeForTheBaselineAmount`：不猜账本币种。
   - `RecurringOccurrenceHost` `RecurringOccurrenceRoute.kt` L53–55：`paymentCurrency == null` **整张** `ManualExpenseSheet` 不打开。记录本期付款按钮仍在 `RecurringOccurrenceSheet` L75–82，点了没有选择入口。

## 判定

历史单位不跟显示币种重解释：成立。未知旧币种没有用户可达明确选择入口：成立缺口。不得用“不猜 CNY”冒充“用户能选币种”。
