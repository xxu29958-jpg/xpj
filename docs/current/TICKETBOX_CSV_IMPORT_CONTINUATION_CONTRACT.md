# CSV import continuation

## Working contract

| Item | Current decision |
| --- | --- |
| Goal | After applying only part of a CSV batch, a household writer can leave and return through Import, identify the original batch and continue its remaining valid rows once. A viewer can inspect the same ledger's receipts and errors without applying. |
| Allowed changes | After actual cloud behavior RED, extend the existing CSV query owner with a bounded, paginated batch read and shared remaining-row projection; wire Import hub/detail and preserve the original detail on recoverable apply refusal. Move the existing remaining-row read and its direct imports without changing apply, claim or lease behavior. Update only the necessary template fixture and generated OpenAPI query parameters. |
| Forbidden surface | No new import writer, batch identity, schema, lease/retry state machine, content-based reupload merge, financial confirmation, Android workflow or Windows lifecycle action. No local PostgreSQL/Gradle/long tests. |
| Done checks | Actual no-database route/template RED and six cloud PostgreSQL behavior counterexamples precede implementation. The five narrow pure cases must turn GREEN; run Ruff, actual OpenAPI generation/check, diff checks and each direct producer's scope classifier locally. The unchanged six PostgreSQL cases and affected integration gates must pass on the controller's next exact cloud candidate. |
| Evidence | Start `1a3bbf9a6401cbafcb3178be8953d626e6586cfe`, tree `a339d7401907b7e6d2edf400b7beef9b9320b373`, branch `codex/csv-import-continuation-20260906`, clean. This integration base contains Income/Capture/Web candidates; it is not asserted to be independently qualified main. Results below distinguish execution from source-only probes. |

Authority: the current full Goal and September 6 Owner/controller FIX govern this slice;
the final August 26 Product contract §§6.1–6.3/6.8 and post-G2 contract Gates P1/P2
require authorized capture/import, truthful intermediate results and recoverable user tasks.
The final Windows contract §18 does not authorize host work here. Fresh G2 stays CLOSED;
repair/reinstall/uninstall/upgrade/downgrade/complete backup/restore and Cut C/D/E stay HOLD.

## Task meaning and retained state

The saved `CsvImportBatch` and its `CsvImportRow` records are the original task. Uploading
another file creates a different task even when its name/content matches. Returning to an
existing task never calls preview again and never changes its public ID, row IDs or row
idempotency keys (`csv-import:{batch.public_id}:{row.line_number}`). Applied expenses stay
pending until the existing review/confirmation owner is invoked.

Existing `valid_rows` records the number of valid rows at parsing time. It does not shrink
when a later row becomes `insert_failed`; neither `valid_rows - applied_rows` nor the batch
status alone proves that another apply can do useful work. `_claim_csv_import_rows` selects
only `valid`; stale `applying` rows are recovered by the existing lease owner. The existing
`_remaining_importable_rows` counts `valid` and `applying`. The error download reads
`error` and `insert_failed`, and neither status can be retried by apply.

| Current row facts | User task and truthful projection |
| --- | --- |
| `valid` or `applying` remains | Continue the original effective remainder. A held lease can refuse temporarily; retain the original batch and let the established owner decide later admission. Do not reclaim or release a lease from a read. |
| No effective remainder, with `error`/`insert_failed` | View the original result and download the failed rows to correct and upload as a new task. Do not advertise another apply/Retry or call this a perpetually unfinished import. Existing applied rows may still link to review. |
| All rows applied, no errors | Completed import receipt; no further apply. Existing pending-review link remains appropriate. |
| Every input row invalid | Error receipt with an error download, no apply and no claim that anything entered pending review. |
| Header-only/zero-row batch | Existing readable empty receipt; no invented pending result, rows or retry transition. |

Import exposes a bounded, paginated recent-batch read for the selected ledger. Continue and
View/error actions remain distinct. Pagination must leave older unfinished work reachable;
a fixed latest-N list with no continuation is insufficient. This is a read of existing
history, not a new archive/dismiss lifecycle or status mutation. Count/action projection is
owned by the read service and shared by hub and detail; templates do not invent row facts.

## Before-change impact closure

| Producer / consumer | Existing chain and impact | Required proof / retirement |
| --- | --- | --- |
| Navigation | `pending.html`, `_sidebar_nav.html`, `_mobile_nav.html`, Owner `index.html` → `/web/import`; both API/Web routers are registered in `main.py`. | Existing entries remain; native navigation must find a saved batch without a remembered URL. No new Owner import surface. |
| Preview writer | `web_import_preview` / `post_csv_import_batch` → `create_csv_import_batch` → `_create_csv_import_batch_record`, row insertion, commit. Each upload creates a new public ID. | Same-file reupload remains a new task; old batch/expenses do not mutate. No change to create/parse semantics. |
| Lookup / hub | `web_import_form` currently reads ledger vocabulary only. `_queries.get_csv_import_batch` requires a known public ID; `list_csv_import_rows` paginates one known batch. | Add one ledger-scoped read in the existing owner, consumed by hub/detail. Test two-ledger non-disclosure and paginated access to older work. |
| Identity / permissions | Web `LocalOnly` plus real session selection → `_resolve_selected_ledger_id`; `_require_selected_ledger_write` gates preview/apply. API uses current app/writer contexts. Desktop apply carries the original session for per-row revalidation. | Retain all guards. Viewer can read the batch/error download, but rendered and direct POST paths cannot apply; no identity inferred from a batch ID. |
| Original apply writer | `web_import_batch_apply` / API apply → `_apply` → batch lease → valid-row claims → pending Expense → count finalization; same-row key lookup precedes insert. | Native two-row apply-one/leave/return/apply-one preserves the first Expense ID and leaves exactly two pending expenses. Existing lease/idempotency tests stay authoritative for their exercised mechanisms. |
| Failure / old exit | Web apply catches every AppError and redirects to `/web/import`, losing the current task. Active lease returns `invalid_request`/409. | Recoverable refusal returns to the original ledger/batch with readable reason. Retire this losing redirect only for recoverable cases; missing/inaccessible batches must not produce a redirect loop or leak another ledger. |
| Detail and error consumer | `import_batch.html` uses original `valid_rows > applied_rows` to offer apply; all-invalid uses the success/pending branch. Error CSV already reads only failed rows. | Replace stale-count action selection with the shared read projection. Preserve original failed-row download and partial-success receipt; do not turn failed rows back into valid. |
| API / export / confirmation | API readers/writers retain existing request/response contracts; Web/API export reads confirmed facts, and imported rows reach ordinary pending review. No batch-list Android consumer exists. | No new API/schema/Android command required for Web continuation; existing HTTP import→confirm→stats/export and viewer tests remain. No financial-confirmation claim from import success. |
| Historical direct importer | `import_service.import_rows` has only test consumers; the old `/web/import/confirm` is already a refusal directing users to staged upload. Neither is called by current Web/API create/apply. | Do not add a new reader/writer through this old helper or reopen its retirement in this slice. Only the live staged task is continued. |
| Direct verification producers | Existing native-form PG file, CSV apply-lease/create/integrity/desktop-revalidation/HTTP files; new no-DB route/template file; `ci_gap_trigger_scope`, CI PG lane collector, frozen backend and native Desktop Web consumer. | Classify each touched/planned direct owner independently. A whole-PR green does not prove that each producer selects its required consumer. Tests-only changes must still select PG. |

## Test-first phase

`test_web_import_continuation.py` exercises the actual apply route and the actual detail
template with only database/identity reads isolated. Engine connections are forbidden.
The template shell is replaced only to bound this evidence to batch actions; it does not
prove shared navigation, real authentication, leases or PostgreSQL.

The existing `test_web_import_review_native_forms.py` gains six HTTP/PG cases: member
partial-apply/return/remainder with same-file reupload separated; selected-ledger/viewer;
active lease refusal/expiry; actual partial insert failure; and older valid/error batches
reachable through pagination. They use real staged batches, original apply/row owners and
canonical pending reads. One row-level AppError is injected at the existing processing seam
to produce the real `insert_failed` state; the reader does not manufacture a successful apply.
The existing `web_client` fixture bypasses the test peer's loopback boundary, while ledger
selection, stored membership roles, native CSRF forms and writer rejection remain real. This
does not claim an installed/public-browser enrollment ceremony or process-death qualification.
These six cases are prepared for cloud, not run against a local database.

Actual local command, from `backend`, using the existing `vnext-ci-py311` Python:
`python -B -m pytest --noconftest -p no:cacheprovider -q tests/test_web_import_continuation.py`.
Result: **3 failed / 2 passed in 5.00 seconds**. Failures were the intended consumer outcomes:
active lease returned `/web/import` instead of the original detail; all-invalid detail offered
pending review; partial `insert_failed` still offered apply. Missing-batch refusal and a fully
applied receipt passed as counterevidence. No import/lifespan/database/connection failure was
substituted for behavior RED. Production files stayed unchanged.

### Direct verification selection, before implementation

The existing `classify_ci_paths([single_path])` was executed separately for every row below.
Connected's `scope` job uses the same `ci_scope.py` selector, so `Android=false` means no
emulator execution, not an Android test pass. CI's existing ordinary PostgreSQL collector
discovers the native-form and pure files without adding a manual test registry.

| Exact producer paths | Actual selected lanes | Claim boundary |
| --- | --- | --- |
| `backend/tests/test_web_import_continuation.py`; `backend/tests/test_web_import_review_native_forms.py` | PostgreSQL | This test-only candidate selects the cloud database lane; the new HTTP cases are still unexecuted locally. |
| `backend/app/services/csv_import_batch_service/_queries.py`; `__init__.py` | PostgreSQL, frozen backend | Planned query owner/required export select its direct backend tests and packaging consumer. |
| `backend/app/routes/web_import_export.py`; `backend/app/templates/web/import_export.html`; `import_batch.html` | PostgreSQL, frozen backend, Desktop, native Windows | Planned route/template changes also select existing served-Web consumers; no Windows lifecycle action is added. |
| This contract | No heavy lane | Documentation is not executable qualification. |

At the test-first handoff, both test files passed Ruff; AST parsing and `git diff --check`
passed. The changed native-form file remained below 800 lines with all original assertions.
Cloud RED, production implementation, GREEN and final review were still outstanding then.

## Authorized implementation after actual cloud RED

The controller read both complete ordinary PostgreSQL job logs for source
`9f7aaf2c14e0d71336600919f41c477659b188b2`, tree
`fafb6c33b820a983775ab0b9006bac8c06e3053b`, CI `34042134022`:
ordinary 2/2 (`101511259225`) recorded 4 failed / 1855 passed / 3 skipped in 453.41s;
ordinary 1/2 (`101511259270`) recorded 5 failed / 1844 passed / 3 skipped in 482.66s.
Together these two completed jobs recorded **9 failed / 3699 passed / 6 skipped**.
After obtaining this sufficient RED, the controller cancelled the remaining CI run;
this is not an aggregate CI failure or a qualified candidate. CodeQL `34042134087` and
Connected `34042134010` had succeeded and were not cancelled. Their results do not
replace the next production head's full necessary gates.
All six new native-form cases reached their intended behavior failures: five could not
find the original batch on Import, and the active-lease case actually redirected to the hub.
The other three failures were the already observed pure route/template cases. These are
executed behavior RED, not collection, environment or unrelated code-weight failures.

The existing `_remaining_importable_rows` read moves from `_row_claim` into `_queries`.
Its apply/finalization consumers keep the same arguments and `valid`/`applying` meaning;
the old definition physically retires. A single grouped read supplies the same remaining
count to the paginated hub and individual detail projection. Listing includes all receipts,
uses stable newest-first ordering and bounds both page size and effective page. It does
not refresh stored counts, acquire/release leases, or rewrite row or batch status.

Both templates consume that projection for continuation and result state. A nonzero
applied count independently permits review; an error-only or empty receipt never claims
to have entered pending review. Known apply conflicts retain the same batch/ledger and
show failure feedback. Missing or inaccessible batches still return to the hub. The
existing role checks and per-row Desktop revalidation remain on the original writer.
No six-case PG assertion is weakened. The pure template fixture may construct the actual
read projection so it exercises the same status/action inputs as production.

Failure feedback was separately proved before changing either template: the fixed `9f7`
route was loaded in memory with both current templates checked against their original
bytes, then the existing five pure cases were run with added severity/role assertions.
Result: **4 failed / 1 passed / 1 warning in 0.28s** (3.61s process time). Both refusal
redirects lacked `flash_type=error`; both error detail renders still used status/success;
the completed success receipt remained a passing control. The import hub's original
template was then exercised by the existing all-invalid case and also actually failed
its `role=alert` assertion (**1 failed / 4 deselected in 2.77s**). Engine connections were
forbidden throughout. The import warning was reported, not suppressed.

All message producers are included: successful preview/apply keep ordinary success;
preview failure, detail lookup failure, apply refusal, error-download lookup failure and
the existing legacy-confirm refusal explicitly request error feedback. Hub/detail accept
only the finite success/error projection; arbitrary query values never become CSS classes.

## After-change impact closure

| Entry / owner / consumer | Implemented change and retained boundary | Evidence and remaining exit gate |
| --- | --- | --- |
| Selected-ledger Import → `_queries.list_csv_import_batches` → hub | All saved receipts are listed newest-first by creation time and ID, default 20/max 100 per page, with the effective page bounded by the actual total. Previous/next links preserve ledger and page size. Viewer reads the same list; only writers get continuation wording. | Six original PG cases remain byte-unchanged; their new-head execution must prove original-batch return, isolation/viewer and both older-batch variants. |
| Detail → `get_csv_import_batch_progress` → the same read projection | Hub and detail use the actual `valid/applying` count and one result-label projection. Historical `valid_rows` no longer controls actions. Pending-review access requires a nonzero applied count; errors remain downloadable and empty/error-only receipts have no apply loop. | The existing pure template cases now construct the actual `CsvImportBatchProgress`; all original action assertions remain, with both templates also checked for failure severity and success-role preservation. |
| Apply/finalization → `_remaining_importable_rows` | The count owner moved to `_queries`, with one grouped predicate reused by detail and the paginated batch read. `_row_claim`'s old definition is removed. Only imports change in `_apply` and `_apply_lease`; original claim, lease, row key, transactions and per-row identity checks remain. | AST comparison against `9f7` found no changed function bodies in `_apply`/`_apply_lease`; all surviving `_row_claim` functions were unchanged. Cloud apply/lease/idempotency tests remain required. |
| Apply failure → existing redirect owner → original detail | Recoverable refusals preserve the same batch and selected ledger. Missing-batch/unauthenticated failures return to Import; the normal selected-ledger and batch lookup guards still prevent inaccessible batches from rendering. No new preview occurs while returning. | Pure active-lease and missing-batch cases pass with unchanged writer arguments and new error severity. Actual held-lease/expiry recovery is still a new-head PG gate. |
| Preview/apply/lookup/error-download/legacy refusal → hub/detail feedback | All actual failure message producers request error/alert; normal preview/apply results retain success/status. A demoted writer can read the saved result through existing read permissions, without regaining apply permission. | Fixed-original severity RED is recorded above. No new message framework, raw class interpolation or permission bypass was added. |
| Generated API contract / direct verification | Actual OpenAPI generation adds only optional `page`, `page_size`, `flash_type` on `GET /web/import` and optional `flash_type` on detail GET. The route set and all schema components remain equal to `9f7`. | Generation and the existing OpenAPI check ran with Engine connections forbidden. This does not claim API integration or Android execution. |

Each final direct producer was classified individually with the existing selector:

| Exact producer paths | Actual selected lanes |
| --- | --- |
| `backend/app/routes/web_import_export.py`; `backend/app/templates/web/import_export.html`; `backend/app/templates/web/import_batch.html` | PostgreSQL, frozen backend, Desktop, Windows |
| `backend/app/services/csv_import_batch_service/_queries.py`; `__init__.py`; `_apply.py`; `_apply_lease.py`; `_row_claim.py` | PostgreSQL, frozen backend |
| `backend/tests/test_web_import_continuation.py`; unchanged `backend/tests/test_web_import_review_native_forms.py` | PostgreSQL |
| `docs/architecture/openapi_contract.json` | Android, under the existing snapshot-path rule |
| This contract | No heavy lane |

The existing five pure cases passed after implementation (**5 passed in 2.65s**), with
database connections forbidden. Ruff and actual OpenAPI check passed; the original six
native-form PG cases have no diff. Final narrow checks are recorded in the handoff.
No local PostgreSQL, Android build, application, browser or broad suite was run. Production
cloud GREEN, final review and integration qualification remain outstanding; the dirty diff
is reviewable implementation evidence, not a new qualified HEAD.

## Interrupted finalization: admitted P2, test-first follow-up

The controller committed the initial production candidate as
`7de2c9af99c503a540d88636bf1578626a0728cb`, tree
`d6e0514831ac65915f748b0cdedce96e6ebd441e`; independent review then found a real
unclosed result consumer. This follow-up changes tests and this contract only until
actual PostgreSQL behavior RED. It does not authorize a GET writer or a lease change.

| Item | Current bounded decision |
| --- | --- |
| Goal | After the final CSV row commits but batch finalization is interrupted, the original hub/detail and API detail/rows batch projection must expose the actual imported result or downloadable error. |
| Allowed changes now | Extend the existing native-form PostgreSQL test file with the real interrupted producer, preserving all original cases; record its impact and exact cloud selection. Production waits for actual RED. |
| Forbidden surface | No new import/lease/status writer, database schema, API contract change, simulated database terminal rows, local PG/Gradle, commit or push by the worker. |
| Done checks | Real single-row apply commits through the original owner, execution stops before finalize, canonical pending/error reads establish the result, and Web/API readers agree while persisted batch cache/lease stay unchanged. Both applied and insert_failed outcomes matter; valid_rows retains its original preview meaning. |
| Evidence | Fixed starting production `7de2c9af`, clean at handoff. New PG probes are source-only until the controller runs this test-only candidate in cloud; earlier six PG and five pure results do not prove this window. |

| Before producer / consumer | Exact gap and minimal boundary |
| --- | --- |
| `_apply._apply_one_claimed_csv_import_row` / `_mark_csv_import_row_insert_failed` | The success path commits at `_apply.py:275`; the error path commits at `:195`. The subsequent `_finalize_csv_import_apply_success` call at `:397` is the first batch-count refresh. Stopping there leaves a durable terminal row and stale zero batch counters. |
| `_queries.get_csv_import_batch_progress` / `list_csv_import_batches` | The grouped query reads only valid/applying. With a committed terminal row it correctly reports zero remaining, but the progress label still reads cached batch applied/error counts and therefore reports an empty receipt. |
| `import_batch.html` and `import_export.html` | Both still use cached applied/error counts for displayed totals and result/error actions. Detail can hide the real pending/error destination while also offering no apply action; hub can call a nonempty result empty. |
| Canonical pending and error CSV owners | They read the committed Expense or CsvImportRow and can already return the real result. They remain the counterevidence to the stale view; no writer change is needed. |
| API detail and rows readers | `routes/imports.py:49–50` serializes cached batch fields; `_lifecycle.py:239–240` embeds the same stale batch in the row response. Neither the schema nor the current working contract defines these counters as a last-finalized snapshot. Both read consumers must use current whole-batch counts, independently of the row page/status filter, through a read-only response mapping. |
| Persisted count consumer | `_csv_io._refresh_batch_counts:78–89` already defines applied as the applied-row count, inserted_count as that same cumulative count, and errors as error + insert_failed. `_apply_lease:143` invokes it in finalization. The expected single aggregation owner must replace this query too; preserve the existing assignments, transaction/commit point and lease owner. GET must not call this writer. |
| Create response / original preview semantics | `_lifecycle:194–205` constructs parse totals and valid/error counts, writes the rows and commits before returning; `routes/imports.py:40` then serializes the batch. `total_rows` and `valid_rows` are original parse facts, not effective remainder. The same read-only response mapping can serve create without changing these meanings or creation order. |
| Apply success / idempotency success responses | `_apply:397–410` and `_idempotency:84–97` finalize, commit and refresh before building their batch response. Their normal cached counts are already current at that point, unlike an interrupted read. Migrate their batch serialization to the same response mapping while preserving the top-level per-request inserted_count (including zero for an idempotency hit), existing first result and finalize/commit ordering. |
| Expected production correction after RED | Extend one grouped row read to supply remaining, applied and error counts; migrate Web progress/templates, API detail/rows/create/apply batch response mapping and the existing finalized-cache consumer. Keep field names/meanings, stored metadata, apply/finalization positions, leases and row keys unchanged. No second count predicate or GET mutation. |

The new PostgreSQL test uses the existing native preview helper, then the real apply
service with a single-row batch. It injects a caught `KeyboardInterrupt` only at the
finalize seam, after the real row commit; the error variant uses the existing processing
seam to produce a real `insert_failed` commit. No cached counter or terminal row is
manufactured in SQL. This is an actual service execution interruption at a precise
boundary, not a claim of real process death. Subsequent native hub/detail requests are
compared with the existing pending API and error CSV. The test also captures the API detail
and row response batch counters, requiring current applied/error/cumulative inserted counts
while valid_rows remains one. A direct persisted-state read before/after all GET consumers
verifies that the API projection did not repair cached counters or release the lease.

Test-only handoff selection:
`backend/tests/test_web_import_review_native_forms.py::test_native_csv_committed_result_survives_interrupted_finalization[applied]`
and the same node with `[insert_failed]`. These two cases have **not been executed locally**;
their expected current failure is the final observed Web/API counts and missing result
actions, after committed row/canonical-result and unchanged-persistence preconditions pass.
The existing six PG cases and every pre-existing test/helper body and parameterization
were AST-compared with `7de2c9af` and remain unchanged. The file has 410 lines; AST syntax,
Ruff and `git diff --check` passed. No production file or OpenAPI snapshot changed.

Individual current classifier results: this test file selects PostgreSQL; this contract
selects no heavy lane. The directly affected `_queries`, `_csv_io`, `_lifecycle`, `_apply`,
`_idempotency` and `routes/imports.py` paths each select PostgreSQL/frozen backend. The
existing Web route and both templates each select PostgreSQL/frozen backend/Desktop/Windows.
These are actual classifier results, not executed integration results or a production fix.

### Actual interruption RED and authorized correction

The test-only commit `d4aaa346` was merged with the governance candidate and pushed as
source `ee60e2d9143c5ecf08d094461d72d87b24076714`, tree
`813ee06fc27b9d47ee54b0ca3600e396d5b96b60`. CI run `34045491208`, ordinary PostgreSQL
job `101519724884`, executed checkout `57f6b39cc85cf24f51c06b866fe99675bcb052fe`
against that source. It completed with **2 failed / 1856 passed / 3 skipped in 488.45s**.
Both interruption cases reached the final `observed` assertion at native-form test line
404: the applied result still returned API counts `[1, 0, 0, 0]` instead of
`[1, 1, 0, 1]`, and the insert-failed result returned the same stale counts instead of
`[1, 0, 1, 0]`. Both Web pages showed zero counts and an empty receipt; the real pending
or error destination was hidden. Earlier assertions established the committed terminal
row, canonical pending/error result and unchanged persisted cache/lease after GET.
This is actual behavior RED, not fixture, collection or environment failure. The other
ordinary job was still running when this sufficient two-case result was read; this is
not an aggregate CI conclusion.

Production is now authorized within the before-impact boundary. `_queries` will own
one grouped row-count definition for remaining, applied and errors. Web progress will
require that current count value; the existing cache writer and all five batch-response
construction sites will consume it. API mapping creates a response value without writing
the ORM batch. Parse `total_rows`/`valid_rows`, stored status/lease metadata, cumulative
batch `inserted_count`, and the separate per-request apply `inserted_count` retain their
meanings. Existing finalize/commit/identity/key order remains; both old cached Web count
reads and the second applied/error aggregation are retired. All eight PG behavior cases
remain unchanged and require the next exact candidate's cloud execution.

### Interrupted-result implementation and impact closure

| Actual consumer after correction | Shared owner and preserved boundary |
| --- | --- |
| `_queries.get_csv_import_batch_progress` and `list_csv_import_batches` | `_csv_import_row_counts` groups the selected ledger's requested batch IDs once, returning valid/applying, applied, and error/insert_failed counts. Empty batches produce zero counts. `CsvImportBatchProgress` requires this typed `row_counts` value; status and result actions do not fall back to cached batch counts. Existing ledger lookup and bounded page ordering are unchanged. |
| Both Web templates | Hub/detail metrics, continuation, pending review and error-download visibility consume `progress.row_counts`. Original metadata and row pagination/filter controls retain their existing sources. Cached applied/error template reads are physically removed. |
| API create, detail, nested rows, apply and idempotency responses | All five former direct `CsvImportBatchResponse.model_validate(batch)` sites call `build_csv_import_batch_response`. That owner copies current count fields into a response model, without modifying the ORM batch. Rows response counts remain whole-batch values independent of row pagination/status. `total_rows`, `valid_rows`, status, timestamps and lease metadata retain their existing values; top-level apply `inserted_count` remains the actual request's count, including zero for an idempotency hit. |
| Existing `_csv_io._refresh_batch_counts` | This persisted consumer reads the same grouped count owner and performs the same applied/inserted/error assignments. Its old separate status-count query is deleted. `_apply_lease` still owns its call, finalization and lease/commit timing. `_remaining_importable_rows` keeps its existing callers/signature and reads the same count value's remainder. |
| Existing native clients and direct tests | Android/Desktop native sources contain no CSV API DTO consumer. The native Desktop Web surface consumes the changed templates through its existing Windows/PG lanes. All original native-form tests, including eight continuation/interruption behavior cases, have unchanged AST; the five pure cases retain all assertions and migrate only their required progress fixture. |

AST comparison against exact `ee60e2d9` verified that all changed function bodies in
`_apply`, `_idempotency`, `_lifecycle` and `routes/imports.py` differ only by replacing the
five batch-response construction calls. `_apply_lease`, `_row_claim` and the CSV schema
are unchanged. This is source evidence for retained writer ordering, not execution of
the persistence or concurrency gates.

Actual local verification: the five existing no-database cases passed in **3.10s**; Ruff,
changed-file AST syntax and `git diff --check` passed. The existing OpenAPI check reported
**up to date** with `Engine.connect` forbidden; no generated snapshot needed a change.
Each changed service module (`__init__`, `_queries`, `_csv_io`, `_lifecycle`, `_apply`,
`_idempotency`) and `routes/imports.py` independently selected PostgreSQL/frozen backend.
Both templates selected PostgreSQL/frozen backend/Desktop/Windows. Each of the two direct
test files selected PostgreSQL; this contract selected no heavy lane. No selector changes,
local database, build, application or long test run occurred. Production is the
candidate recorded below; the two-case RED above does not itself qualify the correction.

### Executed original CSV behavior GREEN

Reviewed production `adc62d2a` was integrated as source
`cd05cda0574812fc4fa134918f9b9529bf547281`, tree
`73c9b917ef72ea3379e9efd58a97717956cade11`. CI `34048522310` ordinary PostgreSQL
jobs `101527997167` and `101527997110` both passed: respectively 1,858 passed / 3 skipped
in 499.89 seconds and 1,862 passed / 3 skipped in 458.33 seconds. Actual checkout
`ea3e53d4c8af1ef682bdeb87e166d29e31960e79` has the identical tree. The six skips are
Windows Edge/NTFS cases; no CSV case was skipped. The original eight-case CSV file
and ordinary runner are byte-identical to test-first `ee60e2d9`, so the full executed
jobs establish the original behavior group, including both interrupted-finalization
counterexamples. Ordinary jobs publish no per-case XML; this is complete-task/log
evidence, not an independently parsed eight-case XML result.

Independent later readback confirmed CI `34048522310`, CodeQL `34048522260` and
Connected `34048522276` all completed successfully at `cd05cda0`. This closes the CSV
behavior correction and that candidate's cloud gates; it does not resolve the newer
Debt/Facts/governance findings inherited in its parent tree, qualify later integration,
protected merge-main or the full household/RC journey. The final integrated CSV source
still needs its own applicable cloud qualification.


## Qualified Facts integration and pending native producer preservation

Before integration, source b9d8f67b2397d1bb98bc15c451e98880f73a063c has exactly three known pending Desktop test changes: _edge_cdp.py, test_ui_browser_layout.py and test_web_bff_edge_e2e.py. Their full normalized source is identical to Capture e86e9cd42ffc8f3b47efdb956f051463956d2faa, whose exact CI/CodeQL/Connected completed successfully. Commit these existing owned improvements rather than discard them. Python AST parsing passes; no local Edge/native/PG/Gradle execution is performed and no prior result is substituted for this new candidate.

The inherited Facts source will be integrated through qualified 847167f203d22feab66c1aa9afa41bf376293c58, whose tree is byte-identical to protected main acb8f70b486aadf723f75b35f826624268eaa3a0. The merge preview is clean. This preserves the CSV entry, mapping/review, partial import/savepoint receipt and continuation consumers, while replacing inherited obsolete correction admission, binding, projection and recovery paths with the qualified Facts owner. There is no new CSV command, schema, protocol or persistence decision. After that real source integration, record the identical squash-main tree as an ancestor without reapplying it. Original producer changes and all CSV assertions remain. The new combined candidate requires its own exact cloud CI/CodeQL/Connected; protected merge remains after independent main qualification and the preceding slice.
