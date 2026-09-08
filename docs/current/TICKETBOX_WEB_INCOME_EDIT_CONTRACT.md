# Web income-plan editing

Authority: full Goal and latest user rulings → final Gmail contracts → exact
code/runtime. Strengthen Planning without duplicating its revision authority.

## User outcome and impact before construction

Web income cards support create/archive/restore but have no editing task. A
writer needs to correct the real plan, retain input after refusal, understand the
effective month and continue after a cross-client conflict. Earlier immutable
revisions and their forecast meaning must survive every new submission.

| Boundary | Required closure |
|---|---|
| Entries | Income card → native edit form; rendered server forecast month travels with the form rather than being replaced by the calendar at Save |
| Owner | Reuse income_plan_service._delivery.update_income_plan_idempotently, its original typed receipt, actor fingerprint and immutable revision owner; no new writer/state engine |
| Consumers | Web list/editor/forecast, API and Android income delivery retain frequency, one-time month, amount, pay day and intent-month semantics |
| Old success exits | Edit has no existing success path. Invalid/OCC refusal must retain fields/key/token/month; explicit review prepares a new proposal without publishing |
| Persistence/protocol | Existing MonthlyIncomePlan, IncomePlanRevision and idempotency tables/epoch suffice. Repeated original submissions cannot add a revision |
| Recovery | A later-month conflict requires explicit review of the current month and current version; repeatedly resubmitting an older month is not a recovery action |
| Direct producers | Frozen-clock native form replay and month rollover; unchanged earlier forecasts/revisions; failed validation; cross-client later-month OCC; role/ledger guard; existing delivery/revision tests; route classification, OCC carrier inventory and OpenAPI snapshot; actual browser tasks |

This slice starts with executed counterexamples before implementation. Existing
create/archive/restore owners remain; retire any duplicate or bypass introduced
by the edit connection. The product atlas retains overall remaining packages;
exact SHA/run evidence stays in the PR and external qualification directory.
Windows lifecycle HOLDs and the full Goal remain unchanged.

## Impact after construction

The card/editor use the existing delivery and revision owners, including actor
identity and original typed receipt. A rejected form retains its fields, key,
version and month; explicit review prepares the current month/version without
writing. A consumed form with a changed second edit receives that review exit
too. Source-type labels are shared by list/create/edit and their old inline copy
is retired. Route classification, OCC inventory and OpenAPI include the new
native form; existing API schemas and financial storage remain unchanged.
The pre-integration candidate passed real VM browser journeys at 360/768/1440px,
including single-month delivery and consumed-form recovery. After integration
with #394, the shared OCC carrier inventory is 109; the [PR qualification record](https://github.com/xxu29958-jpg/xpj/pull/395)
holds final source, browser, bounded review and candidate/main evidence.
