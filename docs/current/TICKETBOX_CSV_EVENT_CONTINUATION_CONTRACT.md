# CSV financial-event continuation

## User outcome and authority

A household writer can bring a Ticketbox financial CSV back to the chosen ledger,
understand which records already exist, and continue missing purchases and their
refund/chargeback/reversal through explicit review. A refund never becomes a new
positive purchase. The saved batch remains reachable after leaving or a failed
request. Ordinary expense CSV, currency precision, batch limits, partial apply,
failed-row export and viewer inspection remain available and must be strengthened.

This continues the full Goal and the [current atlas](TICKETBOX_CURRENT_PRODUCT_ATLAS.md).
Authority is the Goal/latest user rulings, then the final 2026-08-26 Product
contract §§6.2–6.3/6.8/6.10 and §18, and the post-G2 P1/P2 requirements. Codex is
the explicitly delegated product/engineering decision owner within these boundaries.
The user has reiterated that capabilities may only be strengthened.

The [earlier CSV continuation contract](TICKETBOX_CSV_IMPORT_CONTINUATION_CONTRACT.md)
qualifies the existing batch/lease/receipt task. Its closed slice's prohibition on
changing parse/apply is not a new prohibition on this authorized enhancement.
Keep its established continuation, permissions and recovery outcomes.

Fresh-G2 remains CLOSED and the existing Windows lifecycle HOLDs remain. CSV
review creates authorized business commands; it neither restores an installation
nor imports credentials, memberships, actors or device identities. This slice
does not claim the complete portable dataset/export goal has been delivered.

## Semantic decision

**Decision class:** interpretation of exported financial events and their review
workflow, within delegated product design. The direction, source relationship,
frozen money and need for human confirmation follow the existing fact contract;
the UI and staging mechanism are implementation choices. Writing actual daily
data remains outside this task's test permission. No goal/boundary change is needed.

Chosen behavior:

- Plain expense CSV keeps its current accepted money shapes. The absence of native
  event columns does not invent an exported event identity or merge by merchant,
  amount, filename or equal file bytes.
- Native rows retain their event kind, offset kind, source event/root identity,
  accounting date and recorded money/FX evidence from preview through saved task.
  A reversal may have a zero stream contribution; it remains a reversal rather
  than a free purchase. Unknown or contradictory event data remains visible as a
  correctable row and is never interpreted as an ordinary Expense.
- File identities are provenance, not authority to read another ledger or overwrite
  an existing fact. Resolve only within the selected authorized ledger. An already
  represented event leads to its actual record; reuploading a file creates a new
  batch task, not another financial occurrence. Changed content under a known event
  identity requires visible reconciliation with the existing correction task.
- A missing purchase goes to the existing pending Expense/review owner. A missing
  offset remains a saved review task attached to its source root and can proceed
  through the existing offset command only after a real authorized root is selected
  and confirmed. Never synthesize the gross purchase from a refund or net total.
- Month/category/tag exports may omit the root. Keep the row and offer a route to
  locate the root in the chosen ledger or bring in its source record, then resume
  the same task. Do not call a missing root an imported positive expense or a
  successfully recorded refund.
- Preserve original/home currency, minor units, quote date/source and recorded
  amount. File-supplied quote evidence must be identified as imported evidence;
  it cannot silently rewrite the shared daily-rate table or attest that the current
  provider supplied it. Use existing money and fact owners for validation/review.
- A historical native file with all three quote fields empty remains reviewable.
  The writer supplies this event's positive exact quote and date, whose arithmetic
  must match the file's unchanged original/home amounts. Retain raw file cells;
  save reviewed typed evidence with the canonical result. Never replace a quote
  already present in the file, or update a shared quote table.
- A preview, draft admission, matched existing fact and confirmed new event are
  distinct user results. Import never silently confirms purchases or offsets.
  User confirmation uses current actor/role/OCC and a durable original request key;
  an ACK loss or later refresh failure cannot cause another financial event.

Rejected: keep ignoring event columns; flatten everything to net purchases;
automatically insert confirmed events; merge by approximate content; make all native
exports unusable by refusing them; introduce a second financial writer or import
queue. A format error may refuse that row's mutation, but usable known events and
their repair/continuation path are part of the completed task.

## Impact closure before implementation

| Responsibility | Real entry/consumer and required change or preservation |
|---|---|
| Producer | `stats_service.export_confirmed_csv` and Web/API export; preserve released columns/order, event/root IDs and frozen FX. Filtered export is allowed and may omit a related root. |
| Admission | API `imports.py`, Web `web_import_export.py`, `import_service` and batch `_lifecycle/_csv_io`; one validated row interpretation must survive persistence and later error download. |
| Saved state | Existing `CsvImportBatch/CsvImportRow`, schema/migration, Pydantic/OpenAPI row views; add only required event provenance and review association. Historical ordinary rows retain their meaning. |
| Apply | Existing row/batch lease and idempotency owners; positive Expense insertion must consume only purchase rows. Match/read/stage are not new confirmed facts. Existing per-row authorization revalidation and partial receipts remain. |
| Identity and duplicates | Source-event identity must not become token/actor identity. Cross-batch replay and concurrent application require a single durable mapping/result in the existing import/fact boundary. Account for the current unique `CsvImportRow.expense_id` and distinguish matched rows from inserted rows in counts. |
| Human review | Existing pending Expense and offset command, money/FX validation, fact receipt and root OCC. Missing roots, conflicts, refusals and accepted-but-refresh-failed states retain the original task and input. |
| Web task | Import hub/detail, paginated rows, status filters, error CSV, original-batch return and links to actual facts; show purchase versus refund/chargeback/reversal before applying or confirming. Preserve native forms/CSRF, errors and read-only viewers. |
| API/other clients | Existing import endpoints have real API callers; additive fields and supported event review must be explicit. Android has no dedicated batch-import workflow; shared confirmed-fact, pending, offset and refresh consumers still need impact checks if their owners/schema change. |
| Downstream | Confirmed stream, facts/revisions, month totals/export, budget/goals, existing relationship impacts and occurrence eligibility consume the same canonical facts; no imported balance or parallel query authority. |
| Former success exits | Retire native offsets falling through the Expense insertion path and losing event fields on staged/error CSV round trips; replace generic “all applied rows are new pending expenses” feedback. Preserve every valid ordinary import path. |

## Direct evidence and completion

Starting source: `e1595f24015545fae954a8e20478b9a6b159588d`; isolated branch
`codex/csv-event-continuation-20260919`. Documentation-only #421's independent
main CI `35449986511`, CodeQL `35449986518` and Connected `35449986484` all succeeded
on that base. They do not qualify this implementation.

The initial production-export → parser → `_row_from_parsed` short counterexamples
executed with no database connection: **7 failed / 2 passed, 3.36 seconds**. Refund,
chargeback, reversal and saved staging lose their event kind; unknown kinds are
accepted as ordinary purchases. CNY and JPY ordinary expense controls pass. The
subsequent unknown-value test data correction does not constitute a GREEN result.
No production code changed for this RED.

Required proof for the complete slice:

- Actual producer/parser/stored-row preservation, ordinary-money controls, unknown
  or contradictory native rows and a corrected error-file round trip.
- Real PostgreSQL/HTTP native export/import/review: same-ledger existing event;
  missing root and later continuation; purchase plus refund/chargeback/reversal;
  foreign and zero-decimal money; partial apply/leave/reopen; same-event reupload
  and concurrency; ACK loss/replay; viewer and cross-ledger non-disclosure.
- Real rendered Web actions and results, canonical facts/totals and preserved
  permission/OCC/receipt semantics. New schema has a real migration test; update
  actual OpenAPI if the wire contract changes. No test substitutes receipt/count
  assertions for the fact and relationship postconditions.
- Small local pure/consumer counterexamples and checks; PostgreSQL, builds and
  affected longer lanes run on the exact cloud candidate. Bounded review followed
  by targeted regression and final-head qualification, then protected merge and
  independent main results. Do not launch ten-minute local suites.

The before/after impact table must be closed against actual changed production
paths before claiming the slice complete. Root judges any further finding against
the real user postcondition and full Goal; a parser-only GREEN is not completion.
The rest of the atlas remains active, including shared accounting time, complete
portability, relationships/plans, cross-client/Backstage, consumer art and exact RC.

## Candidate implementation and bounded review

The candidate uses the existing CSV batch and per-row lease, Expense admission,
frozen-money arithmetic, offset command, root OCC and durable offset receipt.
`CsvImportEvent` is a ledger-local source/result association, not another financial
fact. Historical rows and the unique purchase-creator row remain intact. Offset
fact, revision, receipt, association and reviewed row evidence commit together.
Other saved rows project an already accepted result without cross-row writes.

Web/API preview, persisted rows, error CSV, batch filters/counts and human review
consume the same interpretation. The Web path retains selected root across its
existing edit/confirmation flow. Changed known-source events lead to their actual
record and existing correction task; invalid event rows retain raw cells for file
correction. Android's existing pending/fact/offset consumers receive
the same canonical facts and string-valued FX source; this slice adds no duplicate
Android import queue. Shared reports, relationship effects and plan eligibility
continue through the existing offset writer and financial stream.

Local checks on the work in progress: **75 pure/parser/staging/money/return/Web
tests passed (3.79 s)**. The effective exported time and missing-quote continuation
had **4 failing / 14 passing** targeted controls before their fixes. Ordinary CSV
controls remain in the suite. A quote-precision regression was already rejected
by the existing parser; its control did not require another implementation.

Bounded source review found two FIXes: effective matched status must drive both
filters and counts, and a quote completed in a later batch must become the
canonical accepted source row. Both are implemented with targeted PostgreSQL
regressions written. The shared offset defaults, same-ledger authorization and
transaction boundary remain; no broader architecture change was needed.

The local release audit exposed missing contextual error copy, missing annotations,
the new route's unauthenticated coverage, and the two actual new OCC-bearing route
carriers. Those are corrected; the exact carrier inventory changes from 120 to
122 with no exemption added. Physical file/span growth remains a responsibility
review signal; no threshold or suppression is relaxed.

**Pending:** exact candidate PostgreSQL/HTTP/migration/concurrency and rendered
Web journeys, cloud builds/gates, protected merge and independent main qualification.
Local pure GREEN and source review are not these results, and no daily installation
or data has been changed. The first complete portable-data export, shared accounting
time migration and all remaining atlas outcomes are still separate active work.
