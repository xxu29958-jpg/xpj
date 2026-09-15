# TBX-404-405-RECONCILE capability scan (A01–A08)

**AUDIT_BASE:** `c34efb40b89c4fecd85478888ed68ce84a90f10f` (`Open period payments without a confirmed stream… #414`)  
**Workspace:** `repo`  
**Contracts:** `docs/current/TICKETBOX_FOREIGN_BILL_CONTINUATION_CONTRACT.md`, `docs/current/TICKETBOX_PENDING_COMMAND_ADMISSION_CONTRACT.md`  
**Contrast base (#404):** `bdcb4f20` — used only where regression judgment needed; no wholesale PR dump.

---

## A01 — CSV / upload / OCR / manual / notification → foreign-bill continuation; old writer retirement

| Field | Value |
|---|---|
| **scan** | TRACED |
| **capability** | PRESERVED |
| **fix** | NOT_NEEDED |

### User → owner → persist/submit → consumers → recovery

1. **CSV saved batch:** User uploads CSV → `POST /api/imports/csv` → `POST …/apply` → per-row `Expense(status=pending)` + `apply_currency_payload` → `prepare_pending_expense_fx` staged in same row transaction → `db.commit()` → `submit_pending_expense_fx` dispatches worker → bill detail / pending queue / `/api/tasks` expose `expense_fx` task → explicit `POST /api/expenses/{id}/fx` retry on failure.
2. **Manual foreign capture:** `POST /api/expenses/manual` → `_insert_manual_expense` demotes to `pending` when `_expense_has_pending_fx` → FX task prepared/committed/dispatched like CSV.
3. **Notification draft:** `POST /api/expenses/notification-drafts` → `apply_currency_payload` → same FX staging path.
4. **Upload / OCR:** `handle_upload` → `stage_pending_expense` → `prepare_pending_expense_enrichment` → enrichment worker completes → `prepare_pending_enrichment_completion` → `prepare_pending_expense_fx` (parent→child handoff, A05).
5. **Edit / recognize / retry-OCR:** `edit_expense_submission`, `post_recognize_text`, `post_retry_ocr` all call `prepare_pending_expense_fx` after mutation commit boundary.
6. **Consumers:** Web pending/health (`test_web_foreign_bill_continuation.py`), Android pending list + FX task projection (`ExpenseRepositoryCore.syncPendingFromService`), API task list with `source_expense_id`.
7. **Recovery:** Failed FX preserves bill; `request_pending_expense_fx` explicit retry; scheduler `refill_pending_expense_fx` for bills never admitted (A05).

### Critical edges (c34efb40)

| Edge | Location |
|---|---|
| CSV apply stages FX after expense flush, commits row, then dispatches | `backend/app/services/csv_import_batch_service/_apply.py` — `_commit_csv_import_apply_row` L274–285, L285–286 |
| Manual create → pending FX path | `backend/app/services/expense_service/_create.py` — `_expense_has_pending_fx` demotion L168–170; `create_manual_expense` L218–225 |
| Notification draft FX staging | `backend/app/services/expense_service/_create.py` — `create_notification_draft` L329–333 |
| Upload → enrichment (not direct FX at upload) | `backend/app/routes/_upload_request.py` — `handle_upload` L326–340, L362 |
| Patch/edit restages FX | `backend/app/services/expense_edit_command_service.py` — `edit_expense_submission` L66–77 |
| Recognize-text / retry-OCR restage FX | `backend/app/routes/expenses.py` — `post_retry_ocr` L669–674; `post_recognize_text` L714–719 |
| **`import_rows` writer retired** — no `def import_rows` in `import_service.py`; only parser + batch owner | Searched: `import_service.py`, `grep import_rows` repo-wide — hits are **`csv_import_rows` table** / `list_csv_import_rows`, not legacy writer. Contract L22 aligns. |
| Capture producers integration test | `backend/tests/test_foreign_bill_capture_producers.py` L30–79 (manual, notification, patch, recognize-text) |
| Continuation journey test | `backend/tests/test_foreign_bill_continuation.py` L18–47 (CSV → pending bill + task) |

### #404 contrast

`pending_fx_task_service.py` exists at `bdcb4f20` (same module family). A01 is **not** a regression vs #404 on missing continuation owner; retirement of direct `import_rows` is **pre-#404 contract debt**, confirmed absent at AUDIT_BASE.

---

## A02 — Historical request date vs published FX date; cache / non-trading-day / provider

| Field | Value |
|---|---|
| **scan** | TRACED |
| **capability** | PRESERVED |
| **fix** | NOT_NEEDED |

### Flow

Bill `exchange_rate_date` (household spending day from `apply_currency_payload` / CSV row) is frozen into `PendingFxInput.rate_date`. Worker prefetches via `fetch_pending_fx_reference` → historical path `fetch_reference_rates_for_date`. Resolver `resolve_payload_rate` returns **`effective_date`** (actual publication day, e.g. prior business day). `apply_pending_fx` writes `exchange_rate_date=published`. Cache rows carry `verified_through` only for **closed** dates so arbitrary older quotes do not prove a requested day was checked.

### Critical edges

| Edge | Location |
|---|---|
| Input binds requested date from expense | `backend/app/services/expense_service/_fx.py` — `PendingFxInput.from_expense` L43–51; `rate_date` field L40 |
| Network fetch by requested date | `backend/app/services/expense_service/_fx.py` — `fetch_pending_fx_reference` L78–85 |
| Provider: on/before requested publication | `backend/app/services/fx_rate_provider.py` — `fetch_reference_rates_for_date` L210–220; `_validate_dated_rates` L201–207 |
| Resolver honesty: `effective_date` ≠ requested on weekend/holiday fallback | `backend/app/services/exchange_rate_service.py` — `resolve_payload_rate` docstring L298–303; `get_covered_fx_rate` gate L318–327 |
| Coverage evidence in cache (`verified_through`) | `backend/app/services/fx_rate_provider.py` — `get_covered_fx_rate` L292–307; `cache_reference_rates_for_date` L351–370 |
| Schema: `fx_rates.verified_through` | `backend/migrations/versions/20260912_0001_fx_continuation.py` L23–25 |
| Unrelated old cache ≠ coverage | `backend/tests/test_foreign_bill_continuation.py` — `test_csv_cannot_treat_an_unrelated_older_cache_row_as_historical_coverage` L79–91 |
| Publication date stored on bill | `backend/tests/test_pending_fx_task_service.py` — `test_dated_provider_revises_pending_bill_once…` L57–80 (`PUBLICATION_DATE` 2026-05-29 vs `REQUESTED_DATE` 2026-05-31) |
| Intended day ≠ import day | `backend/tests/test_foreign_bill_continuation.py` L54–55 (`fx_rate_date` 2026-05-04 for 2026-05-03Z spend) |

### Search if missing

N/A — all resolver/cache/provider symbols found at AUDIT_BASE.

---

## A03 — Exact-date override vs per-expense manual rate; auto refresh must not overwrite confirmed/manual

| Field | Value |
|---|---|
| **scan** | TRACED |
| **capability** | PRESERVED |
| **fix** | NOT_NEEDED |

### Two distinct owners

1. **Exact-date manual override (ledger reference table):** `PUT /api/exchange-rates/{ccy}/{date}` → `set_exchange_rate_idempotently` → `ExchangeRate` row keyed by `(tenant, pair, rate_date)` with OCC on `expected_row_version`. Used by shared consumers / debt / planning — **not** the pending-bill per-expense snapshot path.
2. **Per-bill manual rate:** `PATCH` with `manual_exchange_rate` → `_apply_update_currency` → `apply_currency_payload(..., manual_exchange_rate=…)` on **pending** bills only (L126–137). Does not create global dated override unless separately submitted.

**Auto refresh / worker** must not clobber confirmed or manual-ready snapshots:
- `check_pending_fx` returns `no_result` when `fx_status == ready` (L71–72) — worker skips re-application.
- `_has_frozen_snapshot` blocks mutable-rate re-pricing on confirmed/edited ready bills (`_update_currency.py` L48–54, L139–152).
- Scheduled `refresh_ecb_fx_rates` updates **`fx_rates` global table only** (`fx_rate_provider.py` L373+); no expense mutation loop.
- `prepare_pending_expense_fx` no-ops when `fx_rate_auto_sync_enabled` is false or input unchanged (`pending_fx_task_service.py` L164–165, L167–169).

### Critical edges

| Edge | Location |
|---|---|
| Per-bill manual on pending only | `backend/app/services/expense_service/_update_currency.py` — `_apply_update_currency` L126–137 |
| Frozen snapshot / same-currency correction without re-fetch | `_has_frozen_snapshot` L48–54; `_apply_frozen_snapshot_update` L70–113 |
| Worker skips ready bills | `backend/app/services/expense_service/_fx.py` — `check_pending_fx` L71–72 |
| Global manual rate idempotency + OCC | `backend/app/services/exchange_rate_service.py` — `set_exchange_rate_idempotently` L258–285; `_write_manual_rate` L234–255 |
| Per-bill manual does not pollute global rates list | `backend/tests/test_pending_manual_fx.py` — `test_rate_recovery_is_one_bill_snapshot…` L44–68 (`/api/exchange-rates` items empty) |
| Manual rate ≠ auto-confirm | same test L44–76 (confirm only after explicit review) |
| Android queued manual clears stale ready snapshot locally | `android/.../ExpensePendingRepository.kt` — `projectOptimisticExpense` L158–169 |
| Android unit proof | `android/.../ExpensePendingRepositoryOutboxFallbackTest.kt` L68–143 |

### Search if missing

Searched `refresh_ecb`, `auto_sync`, `manual_exchange_rate`, `confirmed.*reval` under `backend/app/services` and `backend/tests/*fx*` — no path found that revalues confirmed expense snapshots from scheduler.

---

## A04 — Persisted FX tasks, claim, worker, restart/cancel/fail; network vs financial txn isolation

| Field | Value |
|---|---|
| **scan** | TRACED |
| **capability** | PRESERVED |
| **fix** | NOT_NEEDED |

### Flow

`BackgroundTask` rows (`task_type=expense_fx`, `source_expense_id`, `input_payload_json` = frozen `PendingFxInput`) → admission lock + capacity → executor `run_task` claims `queued→running` → `run_pending_expense_fx_task` → preflight `resolve_payload_rate` in txn; if miss, **`db.rollback()`** then provider IO → re-check cancel/OCC → `apply_pending_fx` in new txn → result JSON → worker marks `completed`. Fail/cancel/orphan paths preserve bill; `readmit_orphaned_task` for restart.

### Critical edges

| Edge | Location |
|---|---|
| Task type + source expense index | `backend/app/services/pending_fx_task_service.py` — `PENDING_EXPENSE_FX_TASK_TYPE` L41; `latest_pending_expense_fx_tasks` L57–68 |
| Network isolation: rollback before fetch | `_resolve_pending_fx` L312–320 |
| Post-IO task re-read (retirement safety) | `run_pending_expense_fx_task` L353–359 |
| Failure publication without leaking provider URL | `_publish_failure` L325–341 |
| Explicit retry / resume | `request_pending_expense_fx` L258–299; `_resume_task` L220–230 |
| Claim queued→running | `backend/app/services/background_task_worker.py` — `claim_queued_task` L72–86 |
| Capacity admission lock | `backend/app/services/background_task_admission.py` — `_reserve_active_slot` L77–95 |
| Migration `source_expense_id` + enrichment backfill | `backend/migrations/versions/20260912_0001_fx_continuation.py` L26–45 |
| Handler registration | `backend/app/services/background_task_registry.py` L74–79 |
| Provider failure preserves bill | `backend/tests/test_foreign_bill_continuation.py` L126–148 |
| Restart after result commit | `backend/tests/test_pending_fx_task_service.py` — `test_restart_after_result_commit…` L158–180 |
| Network txn isolation assertion | `test_dated_provider_revises…` L69 (`not checked_sessions[-1].in_transaction()`) |

---

## A05 — Capacity reject, pending dispatch, pagination, old task retirement, parent→child, post-submit dispatch

| Field | Value |
|---|---|
| **scan** | TRACED |
| **capability** | PRESERVED |
| **fix** | NOT_NEEDED |

### Critical edges

| Edge | Location |
|---|---|
| Capacity refusal returns `None`, bill kept | `prepare_pending_expense_fx` L139–147; CSV apply still commits expense L285–286 |
| HTTP 503 on explicit FX when full | `request_pending_expense_fx` L272–273 |
| Scheduler refill batch 32 + cursor | `pending_fx_task_service.py` — `_REFILL_BATCH_SIZE` L42; `refill_pending_expense_fx` L181–210 |
| Blocked cursor retained on capacity full | L206–208 |
| 30s tick + startup refill | `fx_rate_scheduler.py` — `_PENDING_FX_TICK_SECONDS` L22; `_scheduler_loop` L158–178 |
| Obsolete task retirement under Expense lock | `_retire_obsolete_fx_tasks` L117–136; `retire_obsolete_task` on input mismatch L134–135 |
| Repeated edits cancel prior queued tasks | `backend/tests/test_pending_fx_task_service.py` — `test_repeated_pending_edits_replace_obsolete_tasks…` L298–330 |
| **Post-commit dispatch** (financial txn separate from executor submit) | `submit_pending_expense_fx` L175–178; CSV L285–286; `edit_expense_submission` L75–77 |
| **Parent→child:** enrichment completion stages FX in same commit as parent complete | `background_task_worker.py` — `_mark_completed` L102–110; `prepare_pending_enrichment_completion` L203–217 |
| Atomic parent+child admission proof | `backend/tests/test_pending_enrichment_task_service.py` L34–99 |
| Two-bill capacity + scheduler admission | `backend/tests/test_pending_fx_capacity_continuation.py` L93–134 |
| Terminal task at front must not starve later bill | same file L204–216 |
| Cross-ledger capacity release | L137–168 |

---

## A06 — FX publish vs concurrent expense edit/confirm; OCC; conversion must not auto-confirm

| Field | Value |
|---|---|
| **scan** | TRACED |
| **capability** | PRESERVED |
| **fix** | NOT_NEEDED |

### Critical edges

| Edge | Location |
|---|---|
| OCC on apply: row_version mismatch → `conflict` | `check_pending_fx` L69–74; input equality L73–74 |
| Apply bumps version, **status stays pending** | `apply_pending_fx` L115–118; test asserts `confirmed_at is None` |
| Confirm blocked without ready FX | `backend/tests/test_foreign_bill_continuation.py` — `test_confirm_does_not_resolve…` L94–118 (`409 exchange_rate_pending`) |
| Stale confirm after conversion rejected | same file L169–171 (`state_conflict` on old `row_version`) |
| Edit during provider/apply → conflict, preserves user edit | `test_cached_preflight_cannot_hide_an_edit_before_the_apply_lock` L107–130 |
| Edit during running FX retires slot | `test_edit_during_running_fx_releases_original_slot…` L345+ |
| FX worker with items/split mismatch → fail or conflict, still pending | `test_fx_worker_keeps_receipt_reconciliation…` L201–234 |
| Explicit human confirm after ready | `test_import_conversion_failure_retry_review_then_confirm…` L172–175 |

### #404 contrast

OCC/conflict semantics are implemented in `expense_service/_fx.py` and covered by tests added in continuation program; no evidence at AUDIT_BASE that #404 `bdcb4f20` removed these guards (same file present at both SHAs).

---

## A07 — Room shared version; pending/confirmed/rejected projections consistency

| Field | Value |
|---|---|
| **scan** | TRACED |
| **capability** | PRESERVED |
| **fix** | NOT_NEEDED |

### Flow

Single `ExpenseDao` / `expenses` table: confirmed stream sync, pending list sync, and **`applyServerExpense`** (detail + dispatcher writes) share **`row_version` monotonic guard**. Pending list merge uses request-scoped prune map; live `fxTask` attached only when response matches cached `id/publicId/rowVersion`. Rejected lifecycle versions upserted but hidden from usable reads via status + undo/receipt rules.

### Critical edges

| Edge | Location |
|---|---|
| Shared DAO authority comment | `ExpenseRepositoryCore.kt` L384–385 |
| Detail/write adoption | `applyServerExpense` — `ExpenseDao.kt` L208–214 |
| Monotonic upsert | `upsertByServerIdForLedger` L196–205; batch L241–245 |
| Pending prune: only unchanged pre-request versions | `applyPendingSyncForLedger` L454–470 |
| Task projection match | `ExpenseRepositoryCore.kt` — `syncPendingFromService` L390–403 |
| Rejection hidden from canonical read in undo test | `PendingRejectUndoRoomTest.kt` L48–51 |
| Pending sync ≠ confirmed cache | `ExpenseDaoContractTest.kt` L280–297 |
| Prune stale pending | same file L301–325 |
| Disk Room publication failure + refresh marker | `ExpenseSnapshotRoomContinuityTest.kt` L84–116 |
| Reject → Done retains original key/body/binding | `PendingRejectUndoRoomTest.kt` L88–110 |

### Search if missing

Searched `confirmed-only mutation cache`, `wholesale pending replacement` — **no** remaining confirmed-only pending mutation cache at AUDIT_BASE (retired per contract L98–99; grep finds only historical comments in `AppDatabase.kt` migrations).

---

## A08 — Accepted command local publish failure; original key/body/binding/OCC/Done/receipt

| Field | Value |
|---|---|
| **scan** | TRACED |
| **capability** | PRESERVED (Android Outbox scope) |
| **fix** | NOT_NEEDED for Android; **PROPOSED** for Web direct pending editor (contract-deferred) |

### Android flow (in scope)

User save/confirm/reject/… → `ExpensePendingRepository.admit` → `OutboxRepository.enqueueExpenseBatch` (binding lease, original key/body/`expectedRowVersion` on row, no inline HTTP) → worker `PatchExpenseDispatcher` / etc. → server success → `publishAcceptedExpense` → on **cache publication failure**, still `DispatchResult.Success` with `cacheRefreshVersion` + `receiptJson` → `markDone`.

### Critical edges

| Edge | Location |
|---|---|
| Admission before HTTP | `ExpensePendingRepository.kt` — `admit` L115–118; `saveExpenseAllowingOffline` L48–54 |
| Batch preserves both patch+confirm | `OutboxRepository.kt` — `enqueueExpenseBatch` L377–388 |
| Payload token on row, not body | `patchIntent` L125–129; `ExpensePendingRepositoryOutboxFallbackTest.kt` L44–46 |
| Cache failure → Success + receipt | `ExpenseAcceptedPublication.kt` L6–17 |
| Dispatcher uses row idempotency + OCC | `PatchExpenseDispatcher.kt` L78–83 |
| markDone with refresh marker | `OutboxRepository.kt` L508–510 |
| Unit: admission no HTTP | `ExpensePendingRepositoryOutboxFallbackTest.kt` L19–47 |
| Unit: cache publication failure | `PatchExpenseDispatcherTest.kt` L64–82 |
| Disk: PATCH accepted, publication throws, Done + refresh | `ExpenseSnapshotRoomContinuityTest.kt` L107–115 |
| Receipt gating on Done | `ExpenseAcceptanceReceipt.kt` L32–33 |

### OUT_OF_SCOPE / contract-known gap (not A08 Android regression)

Foreign-bill contract L32–33 and pending-command contract: **Web pending editor / review actions still hit server before durable client admission**; local-publication failure on **Web** can lose unpersisted original key. At AUDIT_BASE, Web uses server-side `edit_expense_submission` (`_web_expense_edit_command.py` L23) — **no Room Outbox**. This is **explicit FIX/NEXT Capture package**, not closed by Android A08 work.

Searched: `web/` for outbox/admission — **no matches**.

### #404 contrast

Android Outbox fallback tests and `publishAcceptedExpense` pattern present at AUDIT_BASE; no regression signal vs `bdcb4f20` for Android accepted-command continuity.

---

## Summary matrix

| ID | scan | capability | fix |
|---|---|---|---|
| A01 | TRACED | PRESERVED | NOT_NEEDED |
| A02 | TRACED | PRESERVED | NOT_NEEDED |
| A03 | TRACED | PRESERVED | NOT_NEEDED |
| A04 | TRACED | PRESERVED | NOT_NEEDED |
| A05 | TRACED | PRESERVED | NOT_NEEDED |
| A06 | TRACED | PRESERVED | NOT_NEEDED |
| A07 | TRACED | PRESERVED | NOT_NEEDED |
| A08 | TRACED | PRESERVED (Android); Web gap OUT_OF_SCOPE | NOT_NEEDED (Android); PROPOSED (Web pending editor per contract) |

## Qualification notes (parent verify)

- **Executed at AUDIT_BASE:** static trace + test file pointers only; **no** cloud/VM qualification run in this scan.
- **Primary proof producers:** `test_foreign_bill_continuation.py`, `test_foreign_bill_capture_producers.py`, `test_pending_fx_task_service.py`, `test_pending_fx_capacity_continuation.py`, `test_pending_enrichment_task_service.py`, `test_pending_manual_fx.py`, Android `ExpensePendingRepositoryOutboxFallbackTest`, `PatchExpenseDispatcherTest`, `ExpenseSnapshotRoomContinuityTest`, `PendingRejectUndoRoomTest`.
- **UNVERIFIED at runtime:** end-to-end Windows VM CSV journey, cloud CI on exact candidate — contract L75–79 still marks final qualification pending.
