# B06 Android 未提交输入与原月份（AUDIT_BASE `c34efb40`）

扫描：TRACED
当前能力：计划编辑器 PRESERVED；付款表单实际时间未进 origin store（部分缺口）
修复：PROPOSED（若要把 dismiss 后重开的 paid-at 视为任务上下文：把 `expenseTime` 纳入 origin capture）
证据等级：源码 + Compose restoration 测试（计划编辑器）。付款表单进程恢复未跑 connected。

## 计划编辑器（来源 store vs 表单）

- `RecurringEditorSession` 是 presentation state；事实仍在 repository。
- `RecurringEditorRestorationTest`：JPY 记录 + raw amount、完整 target/draft/OCC/attempt 经 `emulateSavedInstanceStateRestore` 保留。
- 这证明**计划编辑**离开/系统保存，不是付款表单。

## 付款未提交输入

Origin store：`RecurringPeriodPaymentSession` SavedStateHandle JSON L39–45 / `remember` L189–195。
字段：binding, series, period, clientRef, merchant, obligationCurrencyCode, planned/captured amount, ledgerHome, category, note, admitted。
**没有 expenseTime。**

表单 state：`ManualExpenseSheet` `rememberSaveable`：amount/currency/merchant/category/note/**expenseTime**（`LedgerManualExpenseSheet.kt` L90–100）。
Sheet 仍挂着时系统保存可恢复时间。`dismissPeriodPayment` 后 `restoreVisibleOrigin` L178–186 再打开 sheet，initials 只有商家/分类/备注/金额（Route L71–76），`expenseTime` 重新 `nowUtcIso()`。

`capturePeriodPaymentDraft` L77–92 在提交瞬间写入 category/note/currency/amount，仍不含时间。

原期次：origin.period 在 SavedState 中；`restoreAdmittedPeriodOccurrence` 用它 `load(session.period)`。未 admitted 的可见 origin 也按 series+period 键恢复。

## 判定

不能把计划编辑 restoration 测试当成付款草稿已证明。实际时间在 dismiss/重开路径会丢。
