# TBX-404-405-RECONCILE — Group A scan (A01–A12)

> **主控：本文件 A07–A11 的 ID 映射与合同 §2.3 不一致。** A07 应为 Room 投影，A08 应为已接受命令本地发布失败。以 `scan-A01-A08.md` / `scan-A09-A12.md` 为准。

**AUDIT_BASE:** `c34efb40b89c4fecd85478888ed68ce84a90f10f`  
**Worktree:** `repo`  
**Method:** source-only call-chain trace; **no tests executed**  
**Contracts:** `TICKETBOX_FOREIGN_BILL_CONTINUATION_CONTRACT.md`, `TICKETBOX_PENDING_COMMAND_ADMISSION_CONTRACT.md`

## ID mapping (§2.3 A — derived from contract impact tables)

| ID | Contract responsibility |
|---|---|
| A01 | Capture/import — CSV saved batches; retire `import_rows` writer |
| A02 | Reference lookup — historical date + actual publication date |
| A03 | Cache and provider — exact-date manual override vs per-bill manual rate |
| A04 | Background execution — task claim/worker/restart |
| A05 | Deferred admission — scheduler 32-row paging |
| A06 | Superseded FX input retirement |
| A07 | Release schema declaration |
| A08 | Pending mutation — Expense OCC conversion; no auto-confirm |
| A09 | Pending command admission — durable before transport |
| A10 | Accepted command local publication failure recovery |
| A11 | Android saved reads — Room DAO version / projections |
| A12 | Product consumers, classification, shared rate consumers, old exits |

---

## A01 — Capture/import (CSV saved batches vs retired `import_rows` writer)

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED

### Contract questions

| Stage | Bind point |
|---|---|
| User entry (Web) | `c34efb40` `backend/app/routes/web_import_export.py` `web_import_preview` L111–135 → `create_csv_import_batch` |
| User entry (Web apply) | `web_import_batch_apply` L198–234 → `apply_csv_import_batch` |
| User entry (API) | `c34efb40` `backend/app/routes/imports.py` (CSV batch create/apply routes; same `csv_import_batch_service`) |
| Producer/adapter | `create_csv_import_batch` / `_parse_csv_import_rows` in `backend/app/services/csv_import_batch_service/_lifecycle.py` L93–204 reuses `import_service.parse_csv_preview` only (parser, not writer) |
| Owner | `backend/app/services/csv_import_batch_service/_apply.py` `_process_csv_import_apply_row` L76–131 creates `Expense(status="pending")` + `apply_currency_payload` |
| Validation/commit | Row claim: `_claim_csv_import_rows` `backend/app/services/csv_import_batch_service/_row_claim.py` L23+; per-row commit L285–286 |
| FX continuation hook | `_apply.py` L274–323: `prepare_pending_expense_fx` → commit → `submit_pending_expense_fx` (task durable before executor) |
| Worker | `expense_fx` handler registered `backend/app/services/background_task_registry.py` L72–77 |
| Read model | `list_imported_expenses` + `_expense_view` on batch detail `web_import_export.py` L167–169 |
| UI return | `import_batch.html` via `web_import_batch_detail` L138–195; pending queue via normal expense list |
| Failure | Row `insert_failed` L95–99; batch lease cleanup `_cleanup_csv_import_apply_*` L134–168; FX executor refusal does not fail CSV row L320–323 |

**Retired `import_rows` writer:** `import_service.py` at AUDIT_BASE contains only `parse_csv_preview` / row validation — **no `import_rows` function**. Legacy table `csv_import_rows` is the **saved-batch staging table** (written by `_insert_csv_import_rows_in_chunks`), not the retired direct importer. Contract-aligned.

**UNRESOLVED:** None for live import path.

---

## A02 — Reference lookup (historical date, publication date)

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED

### Call chain

| Stage | Bind point |
|---|---|
| User retry (Web) | `web_request_expense_fx` `backend/app/routes/web_expense_edit.py` L157–162 → `render_web_fx_action` → `request_pending_expense_fx` |
| User retry (API) | `post_expense_fx` `backend/app/routes/expenses.py` L137–143 |
| Owner admission | `request_pending_expense_fx` `pending_fx_task_service.py` L258–299 |
| Worker preflight | `check_pending_fx` `expense_service/_fx.py` L61–75 (OCC + input match) |
| Cache read | `resolve_payload_rate` `exchange_rate_service.py` L288–328 → `get_exchange_rate` exact date L309–317 |
| Coverage read | `get_covered_fx_rate` `fx_rate_provider.py` L292–308 requires `verified_through >= rate_date` or exact `rate_date` |
| Provider IO (historical) | `fetch_pending_fx_reference` `_fx.py` L78–85 → `fetch_reference_rates_for_date` when `rate_date < today` |
| Provider IO (current) | `fetch_reference_rates` when `rate_date >= today` |
| Apply + honest date | `apply_pending_fx` `_fx.py` L88–118 → `apply_resolved_currency_rate` with `published` effective date from resolver |
| UI | `expense_fx_view` `_web_money_views.py` L342+; template `_expense_fx.html` shows `requested_date` L5 |

**UNRESOLVED:** None.

---

## A03 — Cache/provider; manual exact-date override vs per-bill manual rate

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED

### Distinct owners

| Mechanism | Entry | Bind point |
|---|---|---|
| **Exact-date manual override (ledger rate table)** | Owner/API set rate | `set_exchange_rate_idempotently` `exchange_rate_service.py` L258–285 → `_write_manual_rate` L234–255 on `(currency, home, rate_date)` |
| **Per-bill manual rate (expense snapshot)** | Web edit form field | `apply_currency_payload` L427+ with `manual_exchange_rate` L460–463 |
| **Per-bill manual (Web confirm guard)** | Confirm refuses unreviewed manual FX | `_manual_fx_submission_needs_preview` `_web_expense_confirm_command.py` L50–68 |
| **ECB cache write after fetch** | Worker | `cache_reference_rates_for_date` `fx_rate_provider.py` L351–370 sets `verified_through` only for **closed** dates L362 |
| **Scheduled quote refresh** | Scheduler | `run_fx_sync_once` `fx_rate_scheduler.py` L106–133 → `refresh_ecb_fx_rates` |

**UNRESOLVED:** None.

---

## A04 — Background execution (claim / worker / restart)

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED

### Call chain

| Stage | Bind point |
|---|---|
| Lifespan startup | `main.py` lifespan L182–183: `recover_orphaned_tasks()` then `start_fx_rate_scheduler()` |
| Orphan recovery | `background_task_service.recover_orphaned_tasks` L347+ → `background_task_recovery_service.py` L26+ |
| Handler registry | `runtime_handler_registry()` `background_task_registry.py` L59–79 registers `run_pending_expense_fx_task` |
| Admission | `prepare_enqueue` / `submit_committed` `background_task_service.py`; capacity via `background_task_admission.py` |
| Worker execution | `run_pending_expense_fx_task` `pending_fx_task_service.py` L344–371 |
| Restart readmission | `_can_resume` L213–217; `readmit_orphaned_task` L222–224 `background_task_admission.py` L52+ |
| Explicit retry (HTTP) | `request_pending_expense_fx` L294–298 re-admits same input |
| Status projection | `current_pending_expense_fx_tasks` L87–94 matches expense revision |

**UNRESOLVED:** None.

---

## A05 — Deferred admission (32-row paging, 30s tick)

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED

### Call chain

| Stage | Bind point |
|---|---|
| Scheduler thread | `start_fx_rate_scheduler` `fx_rate_scheduler.py` L182–205; invalid config still starts loop L191–196 |
| Tick loop | `_scheduler_loop` L158–179: `refill_pending_expense_fx(after_id=after_id)` every ≤30s (`_PENDING_FX_TICK_SECONDS` L22) |
| Paging cursor | `refill_pending_expense_fx` `pending_fx_task_service.py` L181–210; `_REFILL_BATCH_SIZE = 32` L42 |
| Per-candidate transaction | L196–205: separate `SessionLocal`, commit, then `submit_pending_expense_fx` |
| Capacity refusal | L206–208: returns `after_id` unchanged (blocked candidate stays first) |
| Separate from quote sync | `_run_scheduled_fx_sync` L142–155 only on configured wall-clock times L170–173 |

**UNRESOLVED:** None.

---

## A06 — Superseded FX input retirement

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED

### Call chain

| Stage | Bind point |
|---|---|
| Automatic prep | `_prepare_automatic_fx` `pending_fx_task_service.py` L150–172 calls `_retire_obsolete_fx_tasks` L163 |
| Explicit retry/request | `_request_for_expense` L293 |
| Retirement action | `_retire_obsolete_fx_tasks` L117–136 → `retire_obsolete_task` `background_task_handler_api.py` L61+ |
| Lock order | Comment L120–121: Expense lock → old tasks by id → admission lock |
| Worker stale guard | `run_pending_expense_fx_task` L353–359 `db.refresh(task, with_for_update=True)` after IO/OCC |

**UNRESOLVED:** None.

---

## A07 — Release schema declaration

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED

### Evidence

| Check | Bind point |
|---|---|
| Migration head | `20260912_0001_fx_continuation.py` adds `background_tasks.source_expense_id`, `fx_rates.verified_through` |
| Release manifest | `distribution/windows/payload/release-manifest.json` `"max_schema_revision": "20260912_0001"` |
| Build gate | `distribution/windows/build/build_installer.ps1` L384–394 compares manifest to `generationProgram.target_revision` |
| Pre-freeze attestation | `backend/app/database/_money_schema_attestation.py` (money schema manifest cardinality) |

**UNRESOLVED:** Cloud qualification of packaged EXE at this exact HEAD not performed in this scan (OUT_OF_SCOPE for source trace).

---

## A08 — Pending mutation (Expense OCC conversion; conversion must not auto-confirm)

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED

### Call chain

| Stage | Bind point |
|---|---|
| Conversion write | `apply_pending_fx` `_fx.py` L88–118 bumps `row_version` via `bump_row_version` L115 |
| Status remains pending | `check_pending_fx` requires `expense.status == "pending"` L67–68; result outcomes `updated/no_result/conflict/not_pending` L55–58 — **no confirm path** |
| Confirm is separate command | `confirm_expense_submission` `expense_review_command_service.py` L100+ (Web: `confirm_web_expense` `_web_expense_confirm_command.py` L142+) |
| Web manual FX two-step | `prepare_web_expense_confirmation` L80–86: `save_before_confirm` gate; manual preview message L117–120 |
| Android confirm | `saveAndConfirmExpense` enqueues Patch+Confirm batch `ExpensePendingRepository.kt` L56–61 |

**Old exit check:** No confirm-time hidden FX refresh in `_fx.py` or confirm service (grep clean).

**UNRESOLVED:** None.

---

## A09 — Pending command admission (durable before transport)

**scan:** TRACED (Android); TRACED with **known Web gap**  
**capability:** IMPROVED (Android); **REGRESSED** (Web — contract FIX/NEXT)  
**fix:** PROPOSED (Web durable admission / draft continuity per foreign-bill contract row “Remaining direct submission owner”)

### Android — TRACED call chain

| Stage | Bind point |
|---|---|
| User: ExpenseEdit save | `ExpenseEditViewModel.save` L371–373 → `saveExpenseAllowingOffline` |
| User: confirm | `confirm` L375–382 → `saveAndConfirmExpense` |
| User: reject / recognize / retry-OCR / not-dup | L385–417 → `*AllowingOffline` methods |
| User: Pending review | `PendingViewModelReviewActions.kt` `patchExpense` / `saveAndConfirm` → `PendingReviewActions` |
| Repository admission | `ExpensePendingRepository.admit` L115–119 → `outbox.enqueueExpenseBatch` |
| Outbox persist | `OutboxRepository.enqueueExpenseBatch` L378–388 `withActiveBinding` → `dao.insertExpenseCommands` |
| Transport (later) | `OutboxDrainEngine` → `PatchExpenseDispatcher` / `ConfirmExpenseDispatcher` / etc. |
| Save+Confirm atomicity | Single `enqueueExpenseBatch` with `[patchIntent, stateIntent(Confirm)]` L59–60 |

### Web — online-first (contract gap)

| Stage | Bind point |
|---|---|
| Save | `web_save` `web_expense_edit.py` L107–154 → `apply_web_expense_form` → `edit_expense_submission` (single HTTP POST, no local outbox) |
| Confirm | `web_confirm` `web_expense_lifecycle.py` L39–79 → `confirm_web_expense` |
| Reject/Undo | `web_reject` L106+ / undo route → `submit_expense_rejection` |

**Gap (contract-aligned):** Foreign-bill contract L32: Web pending-editor paths accept server idempotency but **lack client-side durable admission** before the request; local-publication failure semantics are N/A on Web, but **unpersisted form state** can still be lost on navigation/ACK loss unlike Android Outbox.

**UNRESOLVED:** Web FIX/NEXT scope and target owner (browser draft vs server-side staging) not specified in AUDIT_BASE code.

---

## A10 — Accepted command local publication failure (Done, original key/body/OCC; not Correction)

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED

### Call chain (Android)

| Stage | Bind point |
|---|---|
| Server 2xx received | e.g. `ConfirmExpenseDispatcher.dispatch` L62–63 |
| Cache publish attempt | `publishAcceptedExpense` `ExpenseAcceptedPublication.kt` L6–18 |
| Success path | `DispatchResult.Success(newRowVersion = rowVersion)` L12 |
| Publication failure | catch L15–17: still `Success` with `cacheRefreshVersion` + `receiptJson` (expense acceptance receipt, **not** Correction payload) |
| Done status | Outbox engine marks row Done; refresh marker via `ExpenseRefreshRequirement.kt` L28+ |
| Marker ack | `acknowledgeExpenseRefresh` `ExpenseRepositoryCore.kt` L262–271 |
| Correction separation | `CorrectExpenseDispatcher` / `ExpenseCorrectionSubmissionCard.kt` — separate mutation types; dispatchers do not decode pending commands as Correction |

**UNRESOLVED:** End-to-end cloud ACK-loss replay at exact HEAD not verified (source-only scan).

---

## A11 — Android Room DAO version / pending-confirm-reject projections

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED

### Call chain

| Stage | Bind point |
|---|---|
| Detail/accept write | `cacheServerExpense` `ExpenseRepositoryCore.kt` L239–246 → `expenseDao.applyServerExpense` |
| Version monotonicity | `ExpenseDao.upsertByServerIdForLedger` L241–245 `expense.rowVersion >= existing.rowVersion` |
| Rejection hidden | `applyServerExpense` L212: non-confirmed clears stream offsets; rejected versions not revived L208 comment |
| Pending list sync | `syncPendingFromService` L389–404 → `applyPendingSyncForLedger` L456–471 |
| Request-scoped prune | L463–465: only rows unchanged at request start (`pruneVersions`) |
| Merge not replace | upsert chunks L466–469; **no wholesale list replacement** |
| Live task attachment | L397–402: `fxTask` only when response matches cached `id/publicId/rowVersion` |
| Confirmed stream | `applyConfirmedStreamSyncForLedger` L409–451 with prune scope L428–450 |

**UNRESOLVED:** None for Room ownership model.

---

## A12 — Product consumers, classification, shared rate consumers, old exits

**scan:** TRACED  
**capability:** PRESERVED  
**fix:** NOT_NEEDED (Web draft keep/replace IMPROVED on Android)

### Web/Android review & dirty draft

| Consumer | Bind point |
|---|---|
| Web pending filter | `web_pending.py` L100–101 `missing_fx` filter; counts L214 |
| Web health | `data_quality_service.py` L268 `missing_fx` count |
| Web FX partial | `_expense_fx.html` L1–25; rate retry formaction L25 |
| Android dirty draft consent | `ExpenseReviewAction` `ExpenseFxStatusCard.kt` L72–89 keep/replace dialog |
| Android FX card | L35–69 task status + manual recovery |
| Task poll without overwriting form | `ExpenseEditViewModelCommands.kt` L17 comment; command rows tracked separately L50–52 |
| Missing amount ≠ missing FX | `data_quality_service.py` L147–157 classification; `pendingNeedsFx` domain helper |

### Shared rate consumers

| Consumer | Bind point |
|---|---|
| Debt member FX | `debt_service/_money.py` L170 `resolve_payload_rate` |
| Refund/reversal (Android) | `ExpenseOffsetDispatchers.kt` → outbox before HTTP; `publishAcceptedExpense` on success |
| Plan valuation (latest + real date) | `resolve_valuation_rate` `exchange_rate_service.py` L331–343 → fallback `get_fx_rate_on_or_before` |

### Reject/Undo / occupancy

| Flow | Bind point |
|---|---|
| Reject + idempotent receipt | `submit_expense_rejection` `expense_review_command_service.py` L61–98 |
| Web undo | lifecycle routes → same service `operation="undo_expense"` |
| Android undo admission | `undoRejectExpense` `ExpensePendingRepository.kt` L85–92 |
| Pending occupancy | `actionInProgressIds` `PendingViewModel.kt` L65, L443–491; mixed SaveAndConfirm blocked in tests |
| A/B panel isolation | `ExpenseEditViewModelCommands.kt` L27–31 binding guard; `fxBinding` vs `captureDeferredLedgerBinding()` |

### Old exits (retired)

- No `import_rows` direct writer (A01).
- No confirm-time hidden FX in `_fx.py`.
- `resolve_payload_rate` does not treat arbitrary old cache as coverage without `verified_through` (A02).

**UNRESOLVED:** VM/cloud user-journey qualification at exact HEAD (contract minimum proof) — not run.

---

## Summary

| Metric | Count |
|---|---|
| **TRACED** | 12 / 12 |
| **BLOCKED** | 0 |
| **TODO (unscanned)** | 0 |
| **PROPOSED fix** | 1 area — **A09 Web** pending-command durable admission (contract FIX/NEXT) |
| **UNVERIFIED (needs runtime qual)** | A07 packaging EXE gate; A10 ACK-loss replay; A12 end-to-end VM/cloud journeys |

### Capability rollup

| Status | IDs |
|---|---|
| PRESERVED | A01–A08, A10–A12 |
| IMPROVED | A09 Android (Outbox batch admission) |
| REGRESSED / gap | A09 Web (online-first; no local admission) |
| OUT_OF_SCOPE | Runtime qualification, Gmail contracts (no entry this session) |

### Remaining UNRESOLVED edges

1. **A09 Web:** Foreign-bill contract explicitly deferring Web pending-editor durable admission to Capture package — no implementation at AUDIT_BASE.
2. **A12 qualification:** Contract requires exact cloud + native VM CSV→failure→retry→confirm journey; scan does not substitute for that evidence.
3. **Gmail authoritative contracts:** Not accessed; atlas + slice contracts used as scan authority per HANDOFF.

---

*Generated: 2026-09-15. Source HEAD verified: `c34efb40b89c4fecd85478888ed68ce84a90f10f`.*
