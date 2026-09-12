# Financial changes reach retained Planning and Insights screens

## Outcome and boundary

After an accepted expense change or successful original Outbox replay, returning
to an already opened Planning or Insights screen reads the changed server facts
without a manual refresh. Budget inputs, Goal edits and occurrence-payment choices
retain their original values and OCC until the user submits or discards them.

Keep the modular monolith, existing domain commands, repositories, navigation and
host isolation. A read invalidation is a prompt to query; it is never a financial
fact, an acceptance receipt or evidence that a queued operation has succeeded.
Use existing success and navigation seams; compress duplicated refresh ownership.
Do not create an event bus, a financial cache authority or a new command system.

## Impact closure before construction

| Responsibility | Production paths and required consumer outcome |
|---|---|
| Foreground changes | Ledger/Pending factory callbacks and fact/manual-submission/rule completion reach the retained Plan root, Budget subpage and existing Insights/DataQuality consumers. Local admission does not claim server acceptance |
| Background acceptance | Existing Outbox drain Success settlement after binding verification must invalidate live financial reads; Queued, unknown, protocol failure, conflict and Discarded are not accepted facts. Preserve existing advice-cache classification independently |
| Planning consumers | Budget, spending-goal lists/progress and recurring candidates/occurrences depend on expense facts. Returning saved backstacks must refresh actual queries, not only revision counters |
| Original-task entries | Workspace and obligation Sync must open Budget, Goal creation/edit, Rule, Income and Rate submissions through the graph that owns those destinations. Keep Expense on the outer graph and correction-rate on its registered graph. Stats Budget entry retains its selected month through existing navigation arguments/SavedStateHandle |
| Original user work | Budget refresh keeps dirty form and original pending save; Goal editing keeps its frozen baseline, with current read after editing ends; occurrence refresh must not erase a selected payment or replace its original OCC |
| Existing other consumers | Stats forces its budget query after primary refresh; DataQuality keeps current binding/filter. Income projection has no direct Expense dependency, but its existing plan/rate invalidation must survive convergence. Debt Goal already reloads on route re-entry and adjustment completion; do not claim live cross-client updates from that narrower evidence |
| Storage/protocol/recovery | No new financial storage or request schema for this slice. Original Outbox bytes/key/binding/OCC/receipt stay authoritative; fresh ViewModels perform initial reads after process recreation |
| Direct verification | Real retained Plan and Budget routes, actual completed drain, dirty editor/choice continuity, failure and binding-change cases. Existing revision-only tests are insufficient; retire assertions that require a known stale Plan |

## Proof and exit

Write actual Route and producer counterexamples first. Use short local checks,
then exact-source cloud compilation/unit/Connected qualification and bounded
review. Close the production and consumer table after implementation; remove the
replaced refresh responsibility rather than leaving two current paths.

Current Goal priorities after this slice: recover original direct repayments and
other unknown financial submissions; resolve shared-timezone configuration scope
and export FX evidence; complete budget/debt offline reads and remaining RC tasks.
Those are current-product gaps, not next-version assets or Windows lifecycle work.
Fresh G2 stays CLOSED and full Windows lifecycle stays HOLD.

## Impact closure after implementation

One shell financial revision replaces both old counters/marks across all source
consumers. Outbox Success publishes after Done/receipt storage under the existing
lease; the outer graph observes its retained value without restarting on revision.
Plan, Budget, Stats/DataQuality, Goal list/detail, Income and Recurring queries
consume it. Budget waits for saving to end; Goal detail waits for editing to end.
Occurrence choices and explicitly cleared Income input keep their original basis.
The six original-task routes in both Sync containers use their registered product
graph; Budget entries carry their selected month through existing SavedStateHandle.
Old symbols have no source/test references. No fact/protocol/storage writer changed.

RED at aa8653c7: cloud CI34686622916 ran 2423 unit tests, with only the two new
draft failures. Connected34686622880 ran 275 tests: background Plan refresh and
three Budget navigation cases failed at their real postconditions; two foreground
cases stopped at an invalid scroll action on the fixed confirmation bar, now fixed
without changing assertions. Earlier6326b29a failed test compilation, not business
behavior. New producer tests cover acceptance ordering, refusal and binding scope.
Bounded source review and short Detekt passed. At cb145ed9, 2426 cloud unit tests
reached one new test-cleanup failure: its cancelled ViewModel collector resumed
after Main dispatcher reset. Cleanup now joins cancellation before resetting Main;
the original choice/payload/OCC assertions remain. Final candidate cloud GREEN
remains required; this is an implemented candidate, not a closed slice or RC.
