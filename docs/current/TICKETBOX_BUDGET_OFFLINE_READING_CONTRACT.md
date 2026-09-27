# Previously read monthly budgets remain usable offline

## Outcome and scope

Reopen a previously read month after Android/Room recreation and inspect the
complete original budget, including configured/unconfigured state, currency,
categories and unknown progress. The actual Plans entry, Budget and Insights budget card show
the read's source and time. New months without a saved read remain unavailable.

BudgetRepository stays the query owner. Reuse ReadSnapshot, existing transport
classification, binding/refusal coordination, Room and the existing save owner.
Keep original drafts and Outbox commands intact. A verified save invalidates old
reads; its accepted result cannot be downgraded by an older query. Never store a
save receipt as a newly fetched query.

## Impact closure before construction

| Boundary | Entry, consumer, old exit and direct producer |
|---|---|
| Budget queries | BudgetActions/BudgetRepository and Graph; exact binding, month and timezone; complete BudgetMonthlyDto snapshot, no local financial recomputation |
| User displays | MainNavGraph → PlanRoute → BudgetRoute/BudgetViewModel; StatsBudgetViewModel → StatsUiState → actual overview budget card. Preserve month navigation, raw drafts/OCC and configured/unknown states |
| Background consumer | NotificationRuntimeGraph → BudgetOverspendChecker must use a fresh query. Existing fresh entry stays explicit; a stored overspend snapshot cannot trigger a new notification |
| Accepted save | SaveMonthlyBudgetDispatcher verified original receipt, AppContainer wiring, BudgetSaveRepository observation and both sync surfaces. Invalidate known-stale reads before publishing Done, without changing bytes/key/OCC or claiming an unaccepted save |
| Refusal/recovery | Only transport unavailability can restore a snapshot. HTTP 401/403 clears affected read displays and binding snapshots; late requests cannot refill after clear/refusal/binding change. Malformed responses and protocol refusal remain failures |
| Storage/producers | The existing stats_projection_cache can hold complete BudgetMonthlyDto reads, identified by kind/binding/month/timezone; reuse it if it meets the current requirements instead of creating a parallel cache owner. Existing cleanup already owns binding snapshots. Budget/Stats VM, notification and save-dispatch producers migrate together; Room tests preserve original intents |

## Verification and boundary

Direct producers: BudgetOfflineReadingConnectedTest (actual Plans → Budget after
Room/VM reopen, original read time and Outbox bytes); BudgetOfflineSnapshotConnectedTest
(fixed September JPY/unknown values, unvisited month/timezone, binding/refusal and
actual NotificationRuntimeGraph freshness with a SENT delivery control); BudgetReadAccessTest (both visible consumers clear on 403,
original draft/OCC retained). The Plan entry uses its actual ledger-calendar month so
this test does not expire at a calendar boundary. The reopened graph also replaces
the calendar repository. Notification warmup and the actual graph must read the same
month and query timezone; the SENT control prevents disabled delivery or a cache-key
mismatch from hiding an invalid notification. Its existing fresh-only behavior must
remain green when the display read gains persistence.

Run short local checks; compilation and real Room/Route execution use exact cloud
qualification. Close the changed consumers
and replaced exits after implementation; do not expand into advice generation,
new commands, Windows lifecycle or a generic caching framework.

Status: direct tests prepared against existing production APIs; cloud RED pending.
Production implementation, after-impact closure and qualification remain open.
This reuses the unmerged 980f3a475 preparation, rebased conceptually on the current
product and calendar owners; it does not inherit test qualification. Direct follow-up
coverage still includes the actual Insights card source/time, same-ledger principal
isolation, preserved budget-command bytes, accepted-save invalidation and a delayed
pre-refusal GET. These belong to this budget task, not to #436's merge gates.
