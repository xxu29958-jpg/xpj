# CSV import continuation

## Working contract

| Item | Current decision |
| --- | --- |
| Goal | After applying only part of a CSV batch, a household writer can leave and return through Import, identify the original batch and continue its remaining valid rows once. A viewer can inspect the same ledger's receipts and errors without applying. |
| Allowed changes | This first phase changes only tests and this contract. The eventual slice may add a bounded, paginated batch read to the existing CSV query owner, wire Import hub/detail projections and preserve the original detail on recoverable apply refusal. |
| Forbidden surface | No new import writer, batch identity, schema, lease/retry state machine, content-based reupload merge, financial confirmation, Android workflow or Windows lifecycle action. No local PostgreSQL/Gradle/long tests. |
| Done checks | Actual no-database route/template RED; cloud PostgreSQL counterexamples prepared for native preview, partial apply, return, isolation/viewer, active lease refusal, row-error receipts and finding an older batch through pagination. The controller has reviewed this test-only candidate for cloud submission; production implementation follows actual behavior RED and remains within the existing Goal authorization. |
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

Both test files passed Ruff; AST parsing and `git diff --check` passed. The changed native-form
file remains below 800 lines and retains all original assertions. The bounded local work stops
at a test-first handoff: cloud RED, production implementation, GREEN and final review remain.
