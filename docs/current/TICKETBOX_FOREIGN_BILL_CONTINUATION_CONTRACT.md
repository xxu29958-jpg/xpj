# Import foreign bills and finish their review

## User outcome and scope

After importing/capturing foreign bills, the household can see which conversions
are incomplete, obtain the reference rates effective for the intended dates,
review original and home amounts, and explicitly confirm the bills. Provider
failure preserves the pending bills and gives retry or existing manual-rate entry.
A completed rate fetch is not a confirmed bill or a completed import/review task.

Goal/latest rulings and final Product contract sections 6.2/7/8.1 govern this task.
Reuse the modular monolith, provider/cache, BackgroundTask, Expense edit/confirm,
and actual Web/Android consumers. No importer-specific writer or second job engine.
No revaluation of confirmed facts, 1.1 expansion or Windows lifecycle work.
Start from qualified main 3503359d; #403 subsequently integrated and independently
qualified at 45044f8b; this candidate incorporates that integration.

## Impact before construction

| Responsibility | Required closure |
|---|---|
| Capture/import | Actual CSV saved batches, manual/notification entry, edits and recognition-derived pending bills enter the same conversion continuation; provenance and original date/currency remain. The unused `import_rows` writer has only legacy test callers and must retire with those tests migrated to the saved-batch entry |
| Reference lookup | Fetch by requested historical date and preserve actual publication date/source. An arbitrary older cached row is not proof that the requested date was checked; do not invent a fixed age threshold |
| Cache and provider | Keep manual exact-date overrides and per-bill manual rates distinct. Concentrate any coverage evidence in the existing reference cache; retain configured transport and ECB provenance |
| Background execution | Existing persistent task owner reports queued/running/result/failure and supports bounded retry/restart; network work cannot hold the financial command transaction. A nullable indexed source-expense relation supports direct per-bill queries; migrate the current enrichment source producer and valid stored inputs, rather than scanning task history or matching serialized JSON |
| Release schema declaration | The release manifest's maximum schema must match the actual migration head consumed by the frozen backend; preserve the existing pre-freeze build check. This qualifies packaging of the product change and does not reopen Windows lifecycle |
| Pending mutation | Revalidate status/OCC/current binding after fetching, preserve later user edits and confirmed snapshots, and use the existing Expense owner; conversion does not auto-confirm |
| Product consumers | Web/Android pending queue, bill editor/detail, import result and data-health entries identify blocked bills and return to review; Owner FX status describes actual relevant outcome |
| Actionable classification | A complete original amount awaiting conversion is missing FX, not missing amount. Data-health counts, both pending filters, quick-entry queues and labels must agree; task updates never replace unsaved form fields or OCC |
| Shared rate consumers | Debt member FX, refund/reversal money and historical projections require dated coverage. Current/future plan valuation keeps the latest reference with its actual publication date. Exact manual overrides and frozen reversal/same-date correction snapshots remain; complete their real recovery consumers with direct regression proof |
| Old exits | Retire latest-sync-as-historical-success, cache-before-date-as-coverage and confirm-time hidden FX refresh; a changed conversion requires a separate pending revision and human review |

## Minimum proof

TDD through actual imports/pending commands: old unrelated cache, missing dated
rate, weekend actual publication date, exact manual override, provider failure and
retry, concurrent edit/confirmation, and real task-to-review consumers. Short local
checks; exact cloud qualification plus affected real client verification before
closure. Initial fba9de4f CI34692792826 reproduced all three original CSV/Expense
counterexamples: ordinary2 accepted an unrelated old quote and confirmed newly
resolved money without review; ordinary1 had no durable original-bill task.
Fail-fast cancelled other lanes. This is business RED, not full qualification.

## Implementation and direct verification

The existing cache owns nullable closed-date coverage; BackgroundTask owns the
indexed original-expense relation, admission, worker and restart status. Expense
owns OCC-checked pending conversion. Confirm-time hidden refresh and the unused
direct importer are removed. Exact-date manual overrides and per-bill input stay
on their existing owners; no confirmed fact is revalued.

`test_foreign_bill_continuation` exercises real import, failure, explicit retry,
pending revision, stale-review refusal, confirmation and stats. Capture-producer,
CSV atomicity, task-worker and migration tests cover actor attribution, original
payload, concurrent edits, restart, admission refusal and preserved data. Web and
Android producers cover original-entry navigation and retained drafts; shared
projection tests separate historical coverage from current valuation with actual
reference dates. The first implementation candidate (55062496) failed cloud and
native VM qualification: the pending version bump remained an SQL expression when
the task serialized its result, rolling back every conversion. The existing
transaction now flushes the pending revision before creating the result. The VM
failure and cloud logs are retained; a new exact candidate must repeat the journey.
Task-test scheduling now controls the actual submitter, and legacy confirmation
tests require explicit conversion and review. Shared fact templates no longer
query pending tasks or claim planning valuation metadata. Short checks pass;
cloud/client qualification and final closure remain pending.

Refund create/void now enter the existing Android Outbox before HTTP; its sole
dispatcher retains original binding/key/OCC and exposes typed missing-rate recovery.
The direct POST, Synced success branch, session-only pending chip and unreachable
direct-conflict refresh state are retired. Fact reads consume financial revisions
without publishing another write signal. Web rate recovery retains the original
financial form, including final-submit ledger checks; rate acceptance never submits it.

The post-construction impact check includes dependent receipt items and splits:
FX uses their existing reconciliation/allocation validators before publishing a
pending version. Android adopts the root and matching child versions together;
an incomplete original amount remains an actionable amount gap. Enrichment passes
its bounded slot to FX in worker-owned completion: parent completion and child
admission commit together, then the existing executor submits the child. The old
running-parent admission path is removed; durable-result replay uses the same
completion path. No task status, financial authority or persistence model is added.
Formal review retains five FIX dispositions and rejects the old queued-refund
refresh finding against the existing dispatcher-to-shell-to-Fact refresh chain.
Short transaction/worker counterexamples changed from five failures to 27 passing
checks; real database, Android and final exact-source qualification remain required.

The completion integration exposed a reverse dependency through the service facade.
Prepared execution belongs to the existing registry; committed dispatch and its
conditional failure publication now belong to the existing executor. The worker
and service both use that implementation. The old private service submitter is
retired, including all capture/upload/worker test interceptors. No cycles or debt
allowances are added. The one-slot database fixture obtains the existing currency
write proof before seeding money; its earlier fence refusal did not test capacity.
Review-test source `4ceb9e77` reproduced five short worker/transaction failures,
two database child-state failures and one actual missing-amount row failure among
280 Connected tests. Source `95a72e7e` completed the isolated native Web journey;
the subsequent dependency correction still requires final exact cloud qualification.

| Exit | Direct qualification producer |
|---|---|
| Dated conversion, preserved source and separate review | PostgreSQL foreign-bill/capture/CSV/task/migration tests; frozen-money and valuation tests |
| All real consumers and protocol | Generated OpenAPI, Android DTO/repository/ViewModel tests; Web native-form and Edge drawer tests |
| Durable refund submission and recovery | Offset repository → real dispatcher/Outbox engine ACK-loss regression; sync/manual-rate Connected route |
| User completes the original task | Exact archive in isolated Windows VM: native CSV import → provider failure → retained draft → retry → explicit review/confirm → one counted fact; Android FX Connected route |
| Integration | Bounded review, exact candidate CI/CodeQL/Connected, protected merge and independent main qualification |
