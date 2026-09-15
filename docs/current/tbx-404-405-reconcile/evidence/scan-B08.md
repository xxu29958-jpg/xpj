# B08 Room 已接受原命令的接管（AUDIT_BASE `c34efb40`）

扫描：TRACED
当前能力：clientRef 复用 PRESERVED；会话 `admitted` 与 Room 接受不是同一权威
修复：NOT_NEEDED（未发现第二套 Create writer）；竞态保持 UNVERIFIED
证据等级：源码 + JVM `roomAcceptedCreateReentryReusesOriginalClientRef`。未跑「接收后、UI 标记前」杀进程。

## 链

1. 真正接收：`ExpenseRepositoryCore.enqueueLocalCreate` L541–568：同一 `clientRef` 作为 Outbox `CreateExpense` target + Room 负 ID 投影，一笔 bound 事务。
2. UI 标记：`RecurringPeriodPaymentSession.acceptPeriodPaymentAdmission` L100–109 仅改 origin.`admitted=true`。由 `applyCreateOutcome` 在 `createPeriodPayment` 协程成功后调用（ViewModel L141–145）。
3. 重开：
   - `recordPeriodPayment` L59–72：已有 sessions[series,period] 则复用 **同一 clientRef**，不 mint 新命令。
   - JVM 测试直接 `ledger.createManualExpense` 后 dismiss 再 record，clientRef 不变。
   - `restoreVisibleOrigin` L183：若 `session.admitted` 则**不**把 origin 放回可见表单。
4. 已 admitted 返回期次：`restoreAdmittedPeriodOccurrence` L143–161 清 `periodPaymentOrigin`，只 load 原 period。

## 窗口

若 Outbox/Room 已插入，但进程在 `applyCreateOutcome` 前死：`admitted` 仍 false。再进入会打开可改 body 的 sheet，提交同一 clientRef。后端 `create_manual_expense` fingerprint mismatch → 422；Android 本地 enqueue 是否拒绝改 body 取决于 Outbox 既有 CreateExpense owner，不是本 VM 标志。

不得把 `admitted` 或相同 clientRef 字符串等同于「已证明复用同一已接受命令体」。

## 排除解释

#405 的 `RecurringPaymentJourneyRouteTest` 不在 AUDIT_BASE（PR 405 added，main 无此文件）。现网 JVM 覆盖 clientRef 复用，不覆盖真实 Room 命令体不变。
