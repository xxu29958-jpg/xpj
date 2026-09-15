# Scan A09–A12 — AUDIT_BASE `c34efb40b89c4fecd85478888ed68ce84a90f10f`

**Workspace:** `repo`  
**HEAD at scan:** `c34efb40` (`Open period payments without a confirmed stream… (#414)`)  
**Contracts read:**  
- `docs/current/TICKETBOX_PENDING_COMMAND_ADMISSION_CONTRACT.md`  
- `docs/current/TICKETBOX_FOREIGN_BILL_CONTINUATION_CONTRACT.md`

**Judgment legend:** PRESERVED | IMPROVED | MISSING | REGRESSED | UNVERIFIED

---

## Contract anchors (authoritative claims)

| Contract | Claim | Scan note |
|---|---|---|
| Pending admission | Save/confirm/reject/recognize retain original command **before** transport; Save-and-confirm preserves both steps; reuse Outbox FIFO/OCC; retire direct writers | Android pending repo satisfies admission-first; Web pending editor still online-first (foreign-bill contract line 32) |
| Pending admission | Reject/Undo freeze original acceptance via server idempotency `response_body`; stale receipt must not undo later rejection | Backend + Android Outbox tests present |
| Foreign bill | Product consumers: import result, pending filters, editor, data health, Owner FX status; dirty draft keep/replace; invalid quote config must not stop accepted-bill continuation | Mostly IMPROVED/PRESERVED at this SHA |
| Foreign bill | Shared consumers: refund/reversal, member debt FX, historical vs plan valuation; schema/manifest/DTO at publish boundary | Partial evidence; cloud qualification still open per contract |

---

## A09 — Pending / ExpenseEdit admission, SaveAndConfirm, batch, direct-write retirement

### Summary judgment: **Android IMPROVED; Web MISSING (known contract gap); batch/binding PRESERVED**

### Durable admission BEFORE transport (Android)

| Edge | Judgment | Evidence |
|---|---|---|
| Save admits PatchExpense row before any HTTP | **IMPROVED** | `c34efb40` `android/app/src/main/java/com/ticketbox/data/repository/ExpensePendingRepository.kt` `saveExpenseAllowingOffline` L48–54 → `admit` L115–119 → `OutboxRepository.enqueueExpenseBatch` L377–388 |
| Admission never calls HTTP inline | **IMPROVED** | `c34efb40` `android/app/src/test/java/com/ticketbox/data/repository/ExpensePendingRepositoryOutboxFallbackTest.kt` `online save persists…` L19–47: `assertNull(api.lastIdempotencyKey, "Admission must not attempt HTTP")` |
| Room reopen retains original row/key/payload | **IMPROVED** | `c34efb40` `android/app/src/androidTest/java/com/ticketbox/data/repository/PendingExpenseAdmissionRoomTest.kt` `anOnlineSaveIsDurableBeforeTransportAndKeepsItsOriginalInputAfterRoomReopen` L66–82 |
| ExpenseEdit VM routes save/confirm/reject/recognize through AllowingOffline | **IMPROVED** | `c34efb40` `android/app/src/main/java/com/ticketbox/viewmodel/ExpenseEditViewModel.kt` `save` L371–373, `confirm` L375–382, `reject` L385–387, `recognizeText` L405–413 |
| Pending review actions (patch, save+confirm, bulk confirm) same admission owner | **IMPROVED** | `c34efb40` `android/app/src/main/java/com/ticketbox/viewmodel/PendingViewModelReviewActions.kt` `saveAmountAndConfirm` L132–150 → `repository.saveAndConfirmExpense`; `confirmReadyExpenses` L153–183 → `repository.confirmExpenses`; `patchExpense` L247–264 → `saveExpenseAllowingOffline` |

### SaveAndConfirm two-step

| Edge | Judgment | Evidence |
|---|---|---|
| Single admission batch = Patch + Confirm intents | **IMPROVED** | `c34efb40` `ExpensePendingRepository.kt` `saveAndConfirmExpense` L56–61: `listOf(patchIntent(...), stateIntent(ConfirmExpense, ...))` |
| Both rows durable before worker/transport | **IMPROVED** | `c34efb40` `PendingExpenseAdmissionRoomTest.kt` `saveAndConfirmKeepBothOriginalCommandsWhenTheEditorStopsBeforeTheFirstResponse` L85–113 |
| Unit: confirm admits SaveAndConfirm with reviewed baseline | **PRESERVED** | `c34efb40` `android/app/src/test/java/com/ticketbox/viewmodel/ExpenseEditViewModelTest.kt` `confirmAdmitsSaveAndConfirmTogetherWithTheReviewedBaseline` (grep hit ~L307) |
| Unit: late SaveAndConfirm blocked by another ledger's review | **PRESERVED** | `c34efb40` `android/app/src/test/java/com/ticketbox/viewmodel/PendingCommandBindingTest.kt` `lateSaveAndConfirmCannotSkipAnotherLedgersAmountReview` (grep hit ~L49) |

### FIFO / OCC / binding lease

| Edge | Judgment | Evidence |
|---|---|---|
| Batch insert under binding lease | **PRESERVED** | `c34efb40` `OutboxRepository.kt` `enqueueExpenseBatch` L383–386: `withActiveBinding` + `dao.insertExpenseCommands` |
| Same-target FIFO: new save joins queue, no inline send | **PRESERVED** | `c34efb40` `ExpensePendingRepositoryOutboxFallbackTest.kt` `save joins the existing same-target FIFO without sending inline` L50–65 |
| Per-target FIFO guard documented on core | **PRESERVED** | `c34efb40` `ExpenseRepositoryCore.kt` `hasUnresolvedQueuedMutationsFor` L456–471 |
| Binding mismatch blocks admission after ledger switch | **IMPROVED** | `c34efb40` `PendingExpenseAdmissionRoomTest.kt` `anOldEditorCannotSendOrAdmitItsDraftAfterTheLedgerBindingChanges` L116–135 |
| Bulk confirm: two Confirm rows before transport | **IMPROVED** | `c34efb40` `PendingExpenseAdmissionRoomTest.kt` `readyBatchPreservesBothConfirmIntentsBeforeTransportAndAfterLeavingTheInbox` L138–163 |

### Explicit abandon vs unknown result (VM occupancy + Outbox terminal states)

| Edge | Judgment | Evidence |
|---|---|---|
| Failed/Conflict row blocks new save until dropped | **IMPROVED** | `c34efb40` `PendingViewModelReviewActionsTest.kt` `failedCommandStillOccupiesTheBillUntilItIsExplicitlyDropped` L239–265 |
| Mixed Patch Done + Failed Confirm blocks re-save; drop Confirm releases without “all succeeded” | **IMPROVED** (#413 consumer) | `c34efb40` `PendingViewModelReviewActionsTest.kt` `droppingFailedConfirmAfterPatchDoneReleasesOccupancyWithoutClaimingAllSucceeded` L268–301 |
| Occupancy release when observed row dropped (#409) | **IMPROVED** | `c34efb40` `PendingViewModelCommands.kt` `finishCompletedExpenseCommands` L50–71: `abandoned` filter + `observedCommandRowIds`; field `observedCommandRowIds` in `PendingViewModel.kt` L141, L165 |
| Merge commits (consumers, not separate products) | **IMPROVED** | `0cba9544` (#409) `PendingViewModelCommands.kt`, `PendingUiStateReducer.kt`, sheet tests; `275de599` (#413) refines `abandoned` status check in same `finishCompletedExpenseCommands` |
| Outbox: Undo cannot retarget after cascade / stale rejection | **PRESERVED** | `c34efb40` `ExpenseUndoOriginalRecoveryTest.kt` `successorCascadeAndExplicitRecoveryCannotRetargetAnUndoToALaterRejection` L11–23 |
| Outbox: refused Undo/reject without original receipt not generic retry | **PRESERVED** | `c34efb40` `ExpenseUndoOriginalRecoveryTest.kt` `RefusedUndoAndAnAcceptedRejectionWithoutItsOriginalReceiptCannotBeGenericRetries` L25–38 |

### Migrated direct-write exits physically retired?

| Surface | Judgment | Evidence |
|---|---|---|
| Android pending save/confirm/reject/recognize/mark-not-dup/retry-OCR | **IMPROVED** (retired inline HTTP on admission path) | `ExpensePendingRepository.kt` — all `*AllowingOffline` call `admit` only; HTTP only in dispatchers (`ConfirmExpenseDispatcher.kt` L62, `RejectExpenseDispatcher.kt` L57, `PatchExpenseDispatcher.kt` L82) |
| Android `enqueueStateTransition` IOException fallback | **PRESERVED** (detail-repo only, not pending primary path) | `c34efb40` `ExpenseRepositoryCore.kt` `enqueueStateTransition` L506–538; callers: `ExpenseDetailRepository.kt` L143, L164 only (grep) — **not** `ExpensePendingRepository` |
| Web pending save/confirm/reject | **MISSING** (online-first; no local Outbox) | `c34efb40` `backend/app/routes/web_expense_edit.py` `web_save` L107–154 → `apply_web_expense_form`; `web_expense_lifecycle.py` `web_confirm` L39–79 → `confirm_web_expense` — direct DB/service |
| Contract acknowledges Web gap | **MISSING** (explicit FIX/NEXT) | `TICKETBOX_FOREIGN_BILL_CONTINUATION_CONTRACT.md` L32: “real pending-editor and review actions still try online requests before durable admission” |
| Contract: do not restore direct-Synced exits | **PRESERVED** (Android tests assert Queued/admitted, not Synced shortcut) | `ExpensePendingRepositoryOutboxFallbackTest.kt` L19–47 |

### Batch consumers (Android)

| Edge | Judgment | Evidence |
|---|---|---|
| `confirmExpenses` batch admission | **IMPROVED** | `ExpensePendingRepository.kt` `confirmExpenses` L63–71 |
| Pending VM bulk confirm tracks `bulkCommandRows`, progress | **PRESERVED** | `PendingViewModelReviewActions.kt` L153–183; `PendingViewModelCommands.kt` `publishBulkConfirmProgress` L41–47 |

**A09 overall:** Android pending-command admission chain is **IMPROVED** vs contract intent. Web pending editor remains **MISSING** durable admission (contract-known). No **REGRESSED** Android direct-Synced reintroduction found at this SHA.

---

## A10 — Reject / Undo mixed completion, occupancy, A/B panel isolation (#409, #413)

### Summary judgment: **IMPROVED** (backend PRESERVED; Android VM occupancy/sheet fixes integrated as chain consumers)

Treat **#409 (`0cba9544`)** and **#413 (`275de599`)** as consumers of the reject/undo/SaveAndConfirm occupancy chain — they adjust `finishCompletedExpenseCommands` and sheet reconciliation, not separate product surfaces.

### Original reject version, receipt, re-reject, Undo

| Edge | Judgment | Evidence |
|---|---|---|
| Web single reject carries form idempotency key + OCC | **PRESERVED** | `c34efb40` `backend/app/routes/web_expense_lifecycle.py` `web_reject` L106–180: `reject_idempotency_key`, `expected_row_version`, `submit_expense_rejection(..., operation="reject_expense", ...)` L147–156 |
| Web undo uses form key + OCC | **PRESERVED** | `c34efb40` `web_expense_lifecycle.py` `web_expense_undo` L183–224: `idempotency_key`, `operation="undo_expense"` L206–214 |
| Bulk / duplicate-current reject same service | **PRESERVED** | `c34efb40` `backend/app/routes/web_pending.py` bulk undo L336–345; `web_duplicates.py` L271 (grep) → `submit_expense_rejection` |
| Service freezes original acceptance via idempotency HIT + `response_body` | **PRESERVED** | `c34efb40` `backend/app/services/expense_review_command_service.py` `_replayed_rejection_receipt` L42–58; `submit_expense_rejection` L61–98 |
| Stale receipt cannot undo later rejection (OpenAPI + service) | **PRESERVED** | `c34efb40` `backend/app/routes/expenses.py` comment L614 (grep); `backend/tests/test_expense_undo_reject.py`; `ExpenseStateApi.kt` L32 comment |
| Android Pending seeds Undo from rejected receipt after command Done | **PRESERVED** | `c34efb40` `PendingViewModelCommands.kt` `adoptPendingCommand` L95–101: `RejectExpense` → `undoableExpense = accepted` when not ignored |
| Android undo via Outbox UndoExpense | **PRESERVED** | `c34efb40` `ExpensePendingRepository.kt` `undoRejectExpense` L85–92; `PendingViewModel.kt` `undoReject` L478–496 |
| Undo consumes original rejected version (not cascaded) | **PRESERVED** | `c34efb40` `ExpenseUndoOriginalRecoveryTest.kt` L11–23 (`cascadeFreshToken` + conflict refusal) |

### Patch Done + Confirm abandoned; occupancy release

| Edge | Judgment | Evidence |
|---|---|---|
| #413: drop failed Confirm after Patch Done releases occupancy, no false “completed” | **IMPROVED** | `275de599` → `PendingViewModelCommands.kt` `finishCompletedExpenseCommands` L54–61 (status-aware `abandoned`); test L268–301 above |
| #409: drop observed failed/conflict row releases `commandRowsByExpense` | **IMPROVED** | `0cba9544` → same function L54–71 + `observedCommandRowIds`; test `failedCommandStillOccupiesTheBillUntilItIsExplicitlyDropped` L239–265 |
| SaveAndConfirm admission leaves two row IDs on accept | **PRESERVED** | `PendingViewModelReviewActionsTest.kt` L278: `assertEquals(2, fake.admissions.single().second.rowIds.size)` |

### A/B panel isolation (one bill’s reject must not close another’s edit sheet)

| Edge | Judgment | Evidence |
|---|---|---|
| Reject completion: `closeSheet = false` on accept | **IMPROVED** (#409) | `c34efb40` `PendingViewModelCommands.kt` `acceptExpenseCommand` L17–19: `afterUpdated(..., closeSheet = false, ...)` |
| Reducer: `afterRejected` keeps sheet when another bill still open | **IMPROVED** (#409) | `c34efb40` `PendingUiStateReducer.kt` `afterRejected` L57–66: `closeSheet = false` |
| Test: reject bill A keeps QuickMerchant sheet on bill B | **IMPROVED** (#409) | `c34efb40` `PendingViewModelReviewSheetAndStateTest.kt` `reducerRejectedKeepsAnotherBillsOpenSheet` L157–172 |
| Test: reject completion reconciles open sheet snapshot (#409) | **IMPROVED** | `c34efb40` `PendingViewModelReviewUndoBannerTest.kt` (added in #409 stat); `PendingViewModelReviewSheetAndStateTest.kt` `reducerUpdatedReplacesItemAndRefreshesOpenSheetSnapshot` L175–195 |

**A10 overall:** Reject/undo protocol **PRESERVED** on backend; Android completion/occupancy/sheet isolation **IMPROVED** by #409/#413 as chain consumers.

---

## A11 — Recovery / review surfaces, dirty draft, quote-config vs continuation

### Summary judgment: **PRESERVED / IMPROVED** on traced surfaces; full cloud journey **UNVERIFIED** per foreign-bill contract

### Web/Android import results & review return paths

| Edge | Judgment | Evidence |
|---|---|---|
| Web CSV import hub/detail/progress | **PRESERVED** | `c34efb40` `backend/app/routes/web_import_export.py` L31–38, L94–238: `get_csv_import_batch_progress`, `apply_csv_import_batch` |
| Android BackgroundTask DTO parity | **PRESERVED** | `c34efb40` `android/app/src/test/java/com/ticketbox/data/remote/dto/BackgroundTaskDtoContractTest.kt` L15–49 |
| Pending → editor navigation (foreign bill) | **PRESERVED** (contract cites producers) | Foreign-bill contract L68–69: Web/Android producers for original-entry navigation |

### Pending filters & actionable classification (missing FX ≠ missing amount)

| Edge | Judgment | Evidence |
|---|---|---|
| Web pending filters incl. `missing_fx` | **PRESERVED** | `c34efb40` `backend/app/routes/web_pending.py` L66, L100, L214; template `pending.html` L113–116 (grep) |
| Shared data-quality caliber `missing_fx` | **PRESERVED** | `c34efb40` `backend/app/services/data_quality_service.py` L10–11, docstring L7–36 |
| Android NeedsFx filter; FX-pending not in NeedsAmount/ReadyToConfirm | **IMPROVED** | `c34efb40` `android/app/src/test/java/com/ticketbox/viewmodel/ExpenseFxViewModelTest.kt` `originalMoneyIsFxRecoveryRatherThanMissingAmountOrReadyToConfirm` L148–155 |
| Android filter enum | **PRESERVED** | `c34efb40` `android/app/src/main/java/com/ticketbox/ui/screens/pending/PendingFilters.kt` `NeedsReviewFilter.NeedsFx` L38–41; `applyNeedsReviewFilter` L146+ |

### Editor, data health, Owner status

| Edge | Judgment | Evidence |
|---|---|---|
| Web data-quality page shares API summary | **PRESERVED** | `c34efb40` `backend/app/routes/web_data_quality.py` L28–47 → `data_quality_summary` |
| Owner console FX panel exposes scheduler + config error | **PRESERVED** | `c34efb40` `backend/app/services/owner_console_service/_fx.py` `FxPanelVM.scheduler_config_error` L38–42, L63–69 |
| Expense edit FX card: retry only with complete original input | **PRESERVED** | `c34efb40` `android/app/src/main/java/com/ticketbox/ui/screens/expense/ExpenseFxStatusCard.kt` L67 (grep); `ExpenseEditViewModelFx.kt` `retryFx` guard L33 |
| Task polling refresh does not adopt money/OCC without explicit review | **IMPROVED** | `c34efb40` `ExpenseFxViewModelTest.kt` `taskRefreshNeverAdoptsMoneyOrOccAndExplicitReviewPreservesProtectedDrafts` L45–87 |

### Dirty draft keep / replace

| Edge | Judgment | Evidence |
|---|---|---|
| Form fields survive rotation/process death | **PRESERVED** | `c34efb40` `android/app/src/main/java/com/ticketbox/ui/screens/ExpenseEditScreen.kt` L215–218: `rememberSaveable` rationale |
| Explicit review: `preserveDraft=true` blocks reload, keeps local fields | **IMPROVED** | `c34efb40` `ExpenseEditViewModelFx.kt` `loadFxReview` L46–91: `FxReviewRefusal.SaveDraftFirst`; string `expense_fx_save_draft_first` L183 `strings.xml` |
| Explicit replace: `preserveDraft=false` loads fresh expense+items+splits when snapshots agree | **IMPROVED** | `c34efb40` `ExpenseEditViewModelFx.kt` `applyFxReview` L105–137; test L79–84, L110–145 |
| Must not require stale-version save before reload when user chooses replace | **IMPROVED** | Test L79–84: reload with `preserveDraft=false` without prior save; `confirmCalls` stays 0 L85 |

### Quote-config errors must not swallow accepted-bill continuation

| Edge | Judgment | Evidence |
|---|---|---|
| Invalid daily quote times/timezone: scheduler still runs accepted-bill refill | **IMPROVED** | `c34efb40` `backend/tests/test_fx_scheduler_recovery.py` `test_invalid_quote_schedule_still_continues_accepted_bills_on_the_existing_thread` L143–174: worker starts, `refill_pending_expense_fx` called, `scheduled_quote.assert_not_called()` |
| Config error surfaced without stopping continuation thread | **IMPROVED** | Same test L172–173: `scheduler_config_error is True`; Owner panel reads via `fx_rate_sync_status()` → `_fx.py` L63–69 |
| Foreign-bill integration tests (import → failure → retry → confirm) | **PRESERVED** (backend unit) | `c34efb40` `backend/tests/test_foreign_bill_continuation.py` (grep hits L52, L88, L96) |

**A11 overall:** Review/recovery surfaces and FX-vs-amount classification **PRESERVED/IMPROVED**. End-to-end cloud/VM qualification for foreign-bill journey remains **UNVERIFIED** (contract L71–79, L126).

---

## A12 — Shared consumers: refund/reversal, member debt FX, projection semantics, publish boundary

### Summary judgment: **PRESERVED/IMPROVED at code boundary; publish qualification UNVERIFIED**

Scope: affected publish boundary only (schema manifest, DTOs, shared rate consumers) — not full Windows lifecycle.

### Refund / reversal (ExpenseOffset)

| Edge | Judgment | Evidence |
|---|---|---|
| Create/void enqueue to Outbox before HTTP | **IMPROVED** | `c34efb40` `android/app/src/main/java/com/ticketbox/data/repository/ExpenseOffsetRepository.kt` `enqueueCreate` L117–135, `enqueueVoid` L137–155 |
| Dispatchers registered in AppContainer | **PRESERVED** | `c34efb40` `android/app/src/main/java/com/ticketbox/AppContainer.kt` L228–233 |
| Foreign-bill contract: refund create/void Android Outbox, direct POST retired | **IMPROVED** | Contract L81–83; no direct POST in `ExpenseOffsetRepository` production path at this SHA |
| Refresh requirement includes offset types | **PRESERVED** | `c34efb40` `android/app/src/main/java/com/ticketbox/data/repository/ExpenseRefreshRequirement.kt` L20–21 |

### Member debt FX

| Edge | Judgment | Evidence |
|---|---|---|
| Member settlement command continuity (tests exist) | **UNVERIFIED** (not traced line-by-line this scan) | Files present: `MemberSettlementCommand.kt`, `MemberSettlementBindingAndRecoveryTest.kt`, `MemberSettlementConnectedTest.kt` — **search attempted**; dated-coverage call chain not opened in this pass |
| Backend covered-rate API | **PRESERVED** | `c34efb40` `backend/app/services/fx_rate_provider.py` `get_covered_fx_rate` L292+, `get_fx_rate_on_or_before` L265+ |

### Historical projection vs plan valuation date semantics

| Edge | Judgment | Evidence |
|---|---|---|
| Current/future plan valuation uses latest reference + publication date | **PRESERVED** | `c34efb40` `backend/tests/test_plan_valuation_reference.py` `test_income_estimate_uses_latest_actual_reference_without_claiming_coverage` L36–52: `get_fx_rate_on_or_before` with `TODAY`, exposes `PUBLISHED` date |
| Past forecasts do not borrow current-estimate lookup | **PRESERVED** | Same file L53–56: August historical `expected_amount_cents is None`; `latest_quote == [TODAY]` unchanged |
| Pending FX uses dated publication, not arbitrary old cache | **PRESERVED** | `c34efb40` `backend/tests/test_foreign_bill_continuation.py` L88 comment/assert; `test_pending_fx_task_service.py` `PUBLICATION_DATE` L28, L80 |

### Schema / manifest / DTO consistency (publish boundary)

| Edge | Judgment | Evidence |
|---|---|---|
| Alembic head for FX continuation | **PRESERVED** | `c34efb40` `backend/migrations/versions/20260912_0001_fx_continuation.py` L6 `revision = "20260912_0001"` |
| Release manifest max_schema matches head | **PRESERVED** | `c34efb40` `distribution/windows/payload/release-manifest.json` L9 `"max_schema_revision": "20260912_0001"` |
| Build guard compares manifest to generation program head | **PRESERVED** | `c34efb40` `distribution/windows/build/build_installer.ps1` L384–416 |
| Migration test pins head | **PRESERVED** | `c34efb40` `backend/tests/test_alembic_fx_continuation_migration.py` L19 `_HEAD = "20260912_0001"` |
| Android Room schema 18 includes fxStatus column | **PRESERVED** | `c34efb40` `android/app/schemas/com.ticketbox.data.local.AppDatabase/18.json` L72–73 |
| OpenAPI expense undo OCC token documents stale-banner guard | **PRESERVED** | `docs/architecture/openapi_contract.json` undo body description (grep L11621) |

**A12 overall:** Refund/reversal admission and projection semantics **IMPROVED/PRESERVED** at traced boundaries. Member debt FX consumer proof **UNVERIFIED** in this scan. Final cloud qualification **UNVERIFIED** per contracts.

---

## Grep: callers related to pending admission / SaveAndConfirm / reject / undo vs `web_expense_lifecycle.py`

`web_expense_lifecycle.py` **defines** (does not call external admission helpers):

| Symbol | Lines | Role |
|---|---|---|
| `web_confirm` | L39–79 | → `confirm_web_expense` (online composite save+confirm service) |
| `web_reject` | L106–180 | → `submit_expense_rejection(..., operation="reject_expense")` |
| `web_expense_undo` | L183–224 | → `submit_expense_rejection(..., operation="undo_expense")` |

**Other production callers of `submit_expense_rejection` (same chain, not in `web_expense_lifecycle.py`):**

| Path | Lines | Operation |
|---|---|---|
| `backend/app/routes/web_pending.py` | L336–345 | bulk `undo_expense` |
| `backend/app/routes/web_duplicates.py` | ~L271 | reject (duplicate resolution) |

**Callers of admission / SaveAndConfirm (Android — no Web Outbox equivalent):**

| Pattern | Primary paths |
|---|---|
| `saveAndConfirmExpense` | `PendingViewModelReviewActions.kt` L149; `ExpenseEditViewModel.kt` L381 |
| `saveExpenseAllowingOffline` | `ExpenseEditViewModel.kt` L372; `PendingViewModelReviewActions.kt` L263 |
| `rejectExpenseAllowingOffline` | `ExpenseEditViewModel.kt` L386; `PendingViewModel.kt` L474–475, L538–539 |
| `undoRejectExpense` | `PendingViewModel.kt` L486 |
| `enqueueExpenseBatch` / `admit` | `ExpensePendingRepository.kt` L115–119 |
| `enqueueStateTransition` (legacy IOException fallback, detail repo only) | `ExpenseDetailRepository.kt` L143, L164 |

**Search attempted, not found at `c34efb40`:** in-repo references to merge SHAs `0cba9544` / `275de599` by hash string (commits exist; integration is via merged code paths above).

---

## Cross-cutting verdict table

| Trace | Primary judgment | Blockers / gaps |
|---|---|---|
| **A09** | Android **IMPROVED**; Web pending **MISSING** durable admission | Web online-first remains contract FIX/NEXT |
| **A10** | **IMPROVED** with #409/#413 as occupancy/sheet consumers | — |
| **A11** | **PRESERVED/IMPROVED** on filters, editor, Owner FX, quote-config continuation | Full foreign-bill cloud qualification **UNVERIFIED** |
| **A12** | Refund + projection + manifest **PRESERVED/IMPROVED** | Member debt FX regression proof **UNVERIFIED** this scan |

---

## Evidence commands executed

- `git rev-parse HEAD` → `c34efb40b89c4fecd85478888ed68ce84a90f10f`
- `git log -1 --oneline 0cba9544`, `275de599`
- `git show 0cba9544`, `275de599` (stat + patch for `PendingViewModelCommands.kt`)
- Repository grep for admission, occupancy, reject/undo, FX, schema (paths cited above)

**Not executed:** Gradle/Connected/PostgreSQL/cloud qualification lanes (out of scope for read-only scan).
