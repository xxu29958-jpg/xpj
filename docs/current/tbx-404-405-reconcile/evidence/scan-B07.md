# B07 意图绑定到入队（主控，AUDIT_BASE `c34efb40`）

扫描：TRACED（入队边）
当前能力：REGRESSED（相对旧 #405 `ExpenseManualCreation.bindExact`；文件已不在 main）
修复：PROPOSED
证据等级：源码对照。未跑切账本竞态。

## 链

1. UI：`RecurringOccurrenceRoute` L55–67 仅当 origin.binding == state.access.binding 且币种已知才打开 `ManualExpenseSheet`；`onCreate` 再校验后 `createPeriodPayment`。
2. VM：`RecurringOccurrenceViewModel.createPeriodPayment` L122–146
   - 用 `periodPaymentOrigin`；若 `access.binding != submitted.binding` 直接 return。
   - `ledger.createManualExpense(draft.copy(clientRef=submitted.clientRef, ...))`
   - 协程返回后再比 binding；`applyCreateOutcome` 后 `onAdmitted(clientRef)`。
3. 真正入队：`ExpenseLedgerRepositoryActions.createManualExpense` L88–91
   - `core.ledgerRequestGuard.bind()` **不是** `bindExact`
   - `core.enqueueLocalCreate(bound, draft, clientRef)`
4. `LedgerRequestGuard.bindExact` 仍存在 L29–38，其它仓库在用；本期付款创建未接到该边。

## 旧 #405

- `c0279d86` `ExpenseManualCreation.kt` L24/L34：`bindExact(binding)`。
- 该文件在 AUDIT_BASE **物理不存在**（已退役 owner），现实现收进 `ExpenseLedgerRepositoryActions` 时改成 `bind()`。

## 用户后果

切账本/身份后，若 VM 校验与 enqueue 之间会话已变，`bind()` 可能把原 clientRef 接到**当前**账本，而不是拒绝错目标。VM 前后检查降低窗口，不是入队点的 exact binding。

## 排除解释

- 不是第二套 Outbox。
- 不是 B01 创建计划缺口。
- Web 付款走 `/web/expenses/new` + return_to，不走这条 Android enqueue。
