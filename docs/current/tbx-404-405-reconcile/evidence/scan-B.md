# Group B scan — foreign recurring through actual payment

**AUDIT_BASE:** `c34efb40b89c4fecd85478888ed68ce84a90f10f`  
**Contrast (read-only):** #405 `c0279d865dca15bb1ac1786d66c1119ed0448db6` · #415 `14c9eca8cf6a301a6f0d9c7a7c8dfb0227c424b9` · #412 merge `9a3b50632f7acedc59eb4dfae94b447a762776b5` · #414 merge `c34efb40`  
**Method:** source-only; no tests executed.  
**Contracts:** `docs/current/TICKETBOX_RECURRING_OCCURRENCE_CONTRACT.md` (fulfillment authority); payment-journey contract exists only on #405 tree (`c0279d86:docs/current/TICKETBOX_RECURRING_PAYMENT_JOURNEY_CONTRACT.md`), not on AUDIT_BASE.

## Summary (scan verdict)

| ID | Scan | Capability (AUDIT_BASE) | Contrast |
|---|---|---|---|
| B01 | TRACED | **MISSING** create-entry foreign currency | **PROPOSED** on #415 `14c9eca8` (not merged); **PRESERVED** on #405 `c0279d86` |
| B02 | TRACED | **PRESERVED** edit/unknown handling; create choice **MISSING** (same root as B01) | #415/#405 add create picker |
| B03 | TRACED | **PRESERVED** planning reads / reserve projection | unchanged core |
| B04 | TRACED | **PARTIAL** — record-payment entry wired (#412); series **prefill MISSING** | #405 `_recurring_payment_prefill` absent on main |
| B05 | TRACED | **PARTIAL** — draft stack present; recurring payment_id / full return carry **MISSING** | #405 richer return fields |
| B06 | TRACED | **PRESERVED** period-payment session + Sheet restore (#414) | #405 adds currency picker on legacy unknown |
| B07 | TRACED | **REGRESSED** on AUDIT_BASE (`bind()` at enqueue); **CHANGED** in working tree (`bindExact` on period payment only) | 主控否决本表「PRESERVED」 |
| B08 | TRACED | **PRESERVED** Room admission + `restoreAdmittedPeriodOccurrence` (#414) | #405 `preferredExpenseId` path not on main |
| B09 | TRACED | **PRESERVED** FX/confirm keeps return context; test at `test_web_period_payment_fx_link_journey.py` | #405 full native journey test not on main |
| B10 | TRACED | **PARTIAL** — Web `payment_month`; Android cross-month focus **MISSING** | #405 `preferredExpenseId` + `return_payment_expense_id` |
| B11 | TRACED | **PRESERVED** — reserve clears only on explicit link | confirmed by journey test source |
| B12 | TRACED | **PARTIAL** — most edit/FX/confirm consumers carry context; **reject** drops recurring return | #405 `web_reject` kept `recurring_occurrence` origin |
| B13 | TRACED | **PARTIAL** — multitask hooks exist; full Connected journey producer **MISSING** on main | adapt `RecurringPaymentJourneyRouteTest.kt` intent from #405 |

---

## B01 — Android/Web real create entry (CNY ledger → JPY 1200 / USD 12.34)

**Verdict:** MISSING on AUDIT_BASE · PROPOSED fix on unmerged #415 · PRESERVED on #405.

### AUDIT_BASE chain (locked to ledger home)

| Stage | SHA | path | symbol | lines |
|---|---|---|---|---|
| Web user entry | c34efb40 | `backend/app/templates/web/recurring.html` | create form `#add` POST | 253–285 |
| Web producer | c34efb40 | `backend/app/routes/_web_recurring_presenter.py` | `apply_form_draft` → `create_form.home_currency_code = ctx["home_currency_code"]` | 104–111 |
| Web bind (hidden currency) | c34efb40 | `backend/app/templates/web/recurring.html` | `<input type="hidden" name="home_currency_code">` | 256 |
| Web submit | c34efb40 | `backend/app/routes/web_recurring.py` | `web_recurring_create` → `create_manual_recurring_item` | 214–267 |
| Owner | c34efb40 | `backend/app/services/recurring_item_command_service.py` | `create_manual_recurring_item` | (CREATE_RECURRING_OPERATION) |
| Android user entry | c34efb40 | `android/.../RecurringScreen.kt` → `RecurringEditorSheetHost` | add sheet | via `RecurringRoute.kt` 48–70 |
| Android session | c34efb40 | `android/.../RecurringEditorSession.kt` | `newRecurringEditorSession(null, currency)` locks `home = currency.storageKey` | 115–139 |
| Android form (no picker) | c34efb40 | `android/.../RecurringEditorForm.kt` | `RecurringEditorAmountField` — no `ExpenseCurrencyChoices` | 134–161 |
| Android submit | c34efb40 | `android/.../RecurringEditorSession.kt` | `submit` → `resolveRecurringFormSubmit` → `onCreate` | 83–107 |
| VM / repo | c34efb40 | `android/.../RecurringViewModel.kt` | `saveManual(RecurringManualSaveCommand.Create)` | via `RecurringRoute.kt` 58–59 |

**Failure/recovery:** Web `preserve_original_ledger_form` + draft replay (`web_recurring.py` 236–266); Android sheet retains draft on submit failure (`RecurringEditorSheet.kt` 284–300).

### Contrast #415 `14c9eca8` (not merged)

| Edge | path | symbol | lines |
|---|---|---|---|
| Web currency select | `backend/app/templates/web/recurring.html` | `<select id="rc-add-currency" name="home_currency_code">` | ~create section |
| Web options producer | `backend/app/routes/web_recurring.py` | `ctx["currency_options"] = [currency_code, *sorted(...)]` | `_render_recurring` |
| Android picker | `android/.../RecurringEditorForm.kt` | `ExpenseCurrencyChoices` + `onCurrency` | #405-style |
| Android select | `android/.../RecurringEditorSession.kt` | `selectCurrency(currency)` | #415 |

**Proof gap:** AUDIT_BASE cannot submit JPY/USD from real create UI — currency is ledger CNY only.

---

## B02 — Create choice vs existing records / unknown legacy currency

**Verdict:** PRESERVED for edit & observed candidates · MISSING create choice (B01).

| Case | SHA | path | symbol | lines |
|---|---|---|---|---|
| Edit locked currency | c34efb40 | `backend/app/templates/web/recurring.html` | hidden `home_currency_code` on edit | 157 |
| Edit conflict hint | c34efb40 | `backend/app/routes/_web_recurring_presenter.py` | `_review_form_draft` `currency_conflict` | 129–140 |
| Unknown on edit (Web) | c34efb40 | `backend/app/templates/web/recurring.html` | label “币种待确认”, `review_required` | 172–193 |
| Unknown on edit (Android) | c34efb40 | `android/.../RecurringEditorForm.kt` | `currency == null` → disabled amount | 139–148 |
| Observed candidate | c34efb40 | `backend/app/templates/web/recurring.html` | confirm-candidate readonly amount/currency | 223–247 |
| Legacy unknown at payment (#405 only) | c0279d86 | `RecurringPaymentJourneyRouteTest.kt` | `legacyCommitmentWithoutCurrencyAllowsAnExplicitPayment...` | test name |

**Unresolved:** AUDIT_BASE `RecurringOccurrenceHost` requires non-null `paymentCurrency` (see B06) — unknown **series** currency blocks record-payment UI entirely.

---

## B03 — Planning reads (list, occurrence, budget, valuation)

**Verdict:** PRESERVED on AUDIT_BASE.

| Stage | SHA | path | symbol | lines |
|---|---|---|---|---|
| Web list | c34efb40 | `backend/app/routes/web_recurring.py` | `_render_recurring` → `item_view` | 112–188 |
| Item projection | c34efb40 | `backend/app/routes/_web_recurring_presenter.py` | `item_view` (`home_currency_code`, `baseline_amount_yuan`) | 56–101 |
| Occurrence read | c34efb40 | `backend/app/services/recurring_occurrence_query.py` | `occurrence_response` | 116–139 |
| Reserve (not payment) | c34efb40 | `backend/app/services/recurring_occurrence_query.py` | `reserved_amount_cents=baseline if active and not valid else 0` | 136 |
| Android list | c34efb40 | `android/.../RecurringScreen.kt` | displays `RecurringItem.homeCurrencyCode` | (via VM) |
| Android occurrence | c34efb40 | `android/.../RecurringOccurrenceSheet.kt` | `occurrence.reservedAmountCents` display | 63–64 |
| Budget outstanding | c34efb40 | `backend/app/services/recurring_occurrence_query.py` | `total_outstanding_recurring_cents` | 153+ |

---

## B04 — Record payment for original period

**Verdict:** PARTIAL — entry TRACED (#412); merchant/amount/date prefill from series **MISSING** on main.

### Web chain (AUDIT_BASE)

| Stage | SHA | path | symbol | lines |
|---|---|---|---|---|
| User entry | c34efb40 | `backend/app/templates/web/recurring_occurrence.html` | “记录本期付款” → `record_payment_href` | 78–83 |
| Href producer | c34efb40 | `backend/app/routes/web_recurring_occurrences.py` | `flow_href("/web/expenses/new", return_to="recurring_occurrence", ...)` | 74–82 |
| Return adapter | c34efb40 | `backend/app/routes/_web_expense_return_context.py` | `flow_href` / `recurring_occurrence_origin` | 146–157, 254–257 |
| Manual create GET | c34efb40 | `backend/app/routes/web_expense_create.py` | `web_manual_expense_new` | 210–238 |
| Post-create redirect | c34efb40 | `backend/app/routes/web_expense_create.py` | `return_to == "recurring_occurrence"` → edit with return fields | 331–336 |
| Confirm return | c34efb40 | `backend/app/routes/_web_expense_return_context.py` | `confirm_return_redirect` | 270–281 |

**MISSING on main:** `#405` `_recurring_payment_prefill(db, return_context)` in `web_expense_create.py` (merchant, `currency_code`, `amount_major` from `get_recurring_item`). Not present at `c34efb40`.

### Android chain (AUDIT_BASE, #412+#414)

| Stage | SHA | path | symbol | lines |
|---|---|---|---|---|
| User entry | c34efb40 | `android/.../RecurringOccurrenceSheet.kt` | `onRecordPayment` button | 75–82 |
| Bind | c34efb40 | `android/.../RecurringOccurrenceRoute.kt` | `onRecordPayment = model.periodPayment::recordPeriodPayment` | 50 |
| Origin store | c34efb40 | `android/.../RecurringPeriodPaymentSession.kt` | `recordPeriodPayment` | 52–75 |
| Manual sheet | c34efb40 | `android/.../RecurringOccurrenceRoute.kt` | `ManualExpenseSheet` + `initials` merchant/amount | 56–77 |
| Submit | c34efb40 | `android/.../RecurringOccurrenceViewModel.kt` | `createPeriodPayment` | 122–147 |
| Post-admit nav | c34efb40 | `android/.../PlanNavigationRoutes.kt` | `onOpenManualSubmission` → `manualExpenseSubmissionRoute` | 80–82 |

**Offline:** Android session persists in `SavedStateHandle` (`RecurringPeriodPaymentSession.kt` 42–45, 194–196).

---

## B05 — Web drafts & all recovery exits

**Verdict:** PARTIAL — infrastructure TRACED; recurring-specific return/payment identity incomplete on main.

| Stage | SHA | path | symbol | lines |
|---|---|---|---|---|
| Draft scope | c34efb40 | `backend/app/routes/web_expense_create.py` | `manual_draft_scope` in context | 98 |
| Browser store | c34efb40 | `backend/app/static/web/manual-drafts.js` | `createStore` phases editing/submitted/blocked | 1–100 |
| Form consumer | c34efb40 | `backend/app/static/web/manual-entry.js` | binds `data-manual-draft-scope` | 1–73 |
| Return hidden fields | c34efb40 | `backend/app/templates/web/expense_new.html` | `edit_return_fields` loop | 32–34 |
| Immutable submitted | c34efb40 | `backend/app/static/web/manual-drafts.js` | `submitted_snapshot_is_immutable` | 63–67 |
| Recurring return carry | c34efb40 | `backend/app/routes/_web_expense_return_context.py` | `ExpenseReturnContext.return_recurring_public_id` | 72, 146–155 |

**MISSING vs #405:** `return_payment_expense_id` field and post-create injection (`replace(return_context, return_payment_expense_id=str(created.id))`) — enables cross-month locate (B10). Zero matches on AUDIT_BASE.

**Failure:** `_manual_expense_failure` preserves form + `client_ref` (`web_expense_create.py` 242–328).

---

## B06 — Android unsubmitted input & original month

**Verdict:** PRESERVED session/draft path · REGRESSED vs #405 for **unknown obligation currency** (host gate).

| Stage | SHA | path | symbol | lines |
|---|---|---|---|---|
| Draft capture | c34efb40 | `android/.../RecurringPeriodPaymentSession.kt` | `capturePeriodPaymentDraft` | 77–98 |
| Visible restore | c34efb40 | `android/.../RecurringPeriodPaymentSession.kt` | `restoreVisibleOrigin` | 178–187 |
| After Room admit | c34efb40 | `android/.../RecurringPeriodPaymentSession.kt` | `restoreAdmittedPeriodOccurrence` | 143–162 |
| Route hook | c34efb40 | `android/.../RecurringRoute.kt` | `LaunchedEffect` → `restoreAdmittedPeriodOccurrence` | 41–46 |
| Host gate | c34efb40 | `android/.../RecurringOccurrenceRoute.kt` | `if (... paymentCurrency != null && ledgerHomeCurrency != null)` | 55 |
| Unknown currency | c34efb40 | — | **ManualExpenseSheet not shown** when `occurrence.homeCurrencyCode` null | implied by 55 |

**#405 contrast:** journey test `legacyCommitmentWithoutCurrencyAllowsAnExplicitPayment...` expects user currency choice — **not reachable** on AUDIT_BASE host gate.

---

## 主控核对（勿把本文件 B07 当终判）

[Scan B](a6d2345b-9b89-41b5-b6e8-f7f1df6bc52f) 把 B07 标成 PRESERVED，依据是 VM 前后比 binding + `bind()`。主控对照 #405 `ExpenseManualCreation.bindExact`：入队点 `bind()` 是 **REGRESSED**。工作区已改为期次付款 `createManualExpense(draft, submitted.binding)` → `bindExact`；普通手动创建仍 `bind()`。B12 `web_reject` 硬跳 pending：主控已核对 #405 在 `return_to==recurring_occurrence` 时保留 origin，现网确为回归。

## B07 — Intent binding to admission

**Verdict（子代理原文，已被主控否决）：** PRESERVED — full chain TRACED on AUDIT_BASE.

| Edge | SHA | path | symbol | lines |
|---|---|---|---|---|
| UI submit | c34efb40 | `RecurringOccurrenceViewModel.kt` | `createPeriodPayment` copies `clientRef`, checks `binding` | 122–131 |
| Ledger API | c34efb40 | `ExpenseLedgerRepositoryActions.kt` | `createManualExpense` | 88–92 |
| Guard | c34efb40 | `ExpenseLedgerRepositoryActions.kt` | `core.ledgerRequestGuard.bind()` | 90 |
| Enqueue | c34efb40 | `ExpenseRepositoryCore.kt` | `enqueueLocalCreate(bound, draft, clientRef)` | 541–568 |
| Outbox | c34efb40 | `ExpenseRepositoryCore.kt` | `offlineMutations.outbox.enqueue` type `CreateExpense` | 548–556 |
| Binding mismatch abort | c34efb40 | `RecurringOccurrenceViewModel.kt` | `if (mutableState.value.access?.binding != submitted.binding) return` | 141 |
| Web binding | c34efb40 | `web_expense_create.py` | `_require_manual_form_binding` | 133–150 |

---

## B08 — Room accepted original command takeover

**Verdict:** PRESERVED (#412/#414).

| Stage | SHA | path | symbol | lines |
|---|---|---|---|---|
| Admission flag | c34efb40 | `RecurringPeriodPaymentSession.kt` | `acceptPeriodPaymentAdmission` sets `admitted=true` | 100–110 |
| On success | c34efb40 | `RecurringPeriodPaymentSession.kt` | `applyCreateOutcome` → `acceptPeriodPaymentAdmission` + `dismissPeriodPayment` | 112–123 |
| Restore period | c34efb40 | `RecurringPeriodPaymentSession.kt` | `restoreAdmittedPeriodOccurrence` loads `session.period` | 143–162 |
| Manual submission route | c34efb40 | `ManualExpenseSubmissionRoute.kt` | Outbox-owned `clientRef` → `SyncStatusScreen` | 50–78 |
| Receipt read | c34efb40 | `ManualExpenseCreationProjection.kt` | `describeManualCreation` → `acceptedExpenseId` | 14–18 |

**Distinction:** `admitted` session flag cleared after restore (line 158); durable truth is Outbox row + `acceptedExpenseId` (B08 vs session-only).

**MISSING vs #405:** `observeManualExpense` + `preferredExpenseId` on `ManualExpenseSheet` (`c0279d86:RecurringOccurrenceRoute.kt`).

---

## B09 — Payment through #404 FX / review / confirm

**Verdict:** PRESERVED on AUDIT_BASE (source + journey test).

| Stage | SHA | path | symbol | lines |
|---|---|---|---|---|
| Create pending FX | c34efb40 | `web_expense_create.py` | `create_manual_expense` → redirect to edit | 303–336 |
| FX on edit | c34efb40 | `test_web_period_payment_fx_link_journey.py` | manual rate save | 139–160 |
| Confirm | c34efb40 | `web_expense_lifecycle.py` | `web_confirm` → `confirm_return_redirect` | 39–79 |
| Return to period | c34efb40 | `test_web_period_payment_fx_link_journey.py` | assert confirm → `occurrence_path` month=August | 180–183 |
| Reserve unchanged | c34efb40 | `test_web_period_payment_fx_link_journey.py` | `after_confirm reserved_amount_cents == 2000` | 185–191 |
| Android | c34efb40 | `ManualExpenseSubmissionRoute.kt` | post-admit → `ExpenseEditRoute` | 64–66 |

**Note:** Journey uses API seed for USD series (test producer) — valid for B09/B11, not for B01.

---

## B10 — Return to exact original period & locate this payment

**Verdict:** PARTIAL.

| Mechanism | AUDIT_BASE | #405 |
|---|---|---|
| Web obligation month | `return_month` in `ExpenseReturnContext` | same |
| Web payment search month | `payment_month` GET on occurrence page (`recurring_occurrence.html` 73) | same |
| Web post-create payment id | **MISSING** `return_payment_expense_id` | present in `_recurring_payment_prefill` / redirect |
| Android month restore | `restoreAdmittedPeriodOccurrence` → `load(session.period)` | same |
| Android picker focus | **MISSING** `preferredExpenseId` | `c0279d86:RecurringOccurrenceRoute.kt:73` |
| Android picker filter | `OccurrencePaymentPicker` month + query (`RecurringOccurrenceSheet.kt` 139–157) | same |

**Unresolved edge:** After September payment + return to August, user must manually set payment month to September on Web/Android — no auto-focus to created expense on main.

---

## B11 — Explicit link / undo / reserve

**Verdict:** PRESERVED — TRACED.

| Stage | SHA | path | symbol | lines |
|---|---|---|---|---|
| Record does not link | c34efb40 | `web_recurring_occurrences.py` | `record_payment_href` only builds create URL | 74–82 |
| Confirm does not link | c34efb40 | `test_web_period_payment_fx_link_journey.py` | state stays `unfulfilled` after confirm | 185–191 |
| Link owner | c34efb40 | `recurring_occurrence_command.py` | `set_occurrence_payment` | 94–120 |
| Reserve logic | c34efb40 | `recurring_occurrence_query.py` | `valid = period in paid`; reserve only when not valid | 125–136 |
| Web link UI | c34efb40 | `recurring_occurrence.html` | POST `action=link` | 93–96 |
| Android link | c34efb40 | `RecurringOccurrenceViewModel.kt` | `choose` + `submit` → `repository.enqueue` | 149–186 |
| Zero reserve | c34efb40 | `test_web_period_payment_fx_link_journey.py` | after link `reserved_amount_cents == 0` | 222–224 |
| Clear association | c34efb40 | `recurring_occurrence_command.py` | action `clear` | via payload |
| Reversal → needs_review | c34efb40 | `recurring_occurrence_query.py` | state `needs_review` when linked expense invalid | 126 |

---

## B12 — All return consumers (confirm/FX/reject/correction/fact/…)

**Verdict:** PARTIAL — most edit-flow consumers TRACED; **reject/undo** recurring return **REGRESSED** vs #405.

### `resolve_return_to` bind points (AUDIT_BASE)

| SHA | path | symbol | lines |
|---|---|---|---|
| c34efb40 | `backend/app/routes/_web_expense_return_context.py` | `resolve_return_to` | 163–168 |
| c34efb40 | `backend/app/routes/_web_expense_helpers.py` | confirm/reject error redirects | 84, 405 |
| c34efb40 | `backend/app/routes/web_expense_edit.py` | save redirect | 74 |
| c34efb40 | `backend/app/routes/_web_expense_fact.py` | fact return | 448 |
| c34efb40 | `backend/app/routes/web_expense_correction.py` | correction return | 100, 329 |
| c34efb40 | `backend/app/routes/_web_correction_page.py` | correction page | 142 |
| c34efb40 | `backend/app/routes/web_bill_split.py` | split return | 288 |

### Gap

| Flow | AUDIT_BASE | #405 |
|---|---|---|
| Confirm from recurring journey | `confirm_return_redirect` → occurrence | same (TRACED) |
| Reject/ignore mid-journey | `web_reject` always `_web_redirect("/web/pending", ...)` | kept `return_context` when `return_to=="recurring_occurrence"` |
| Undo | `web_expense_undo` → pending only | (not traced to recurring on #405 either) |

**Lines:** `web_expense_lifecycle.py` `web_reject` 173–180 (AUDIT_BASE).

---

## B13 — Android multitask / cross-client return

**Verdict:** PARTIAL.

| Mechanism | SHA | path | symbol | lines |
|---|---|---|---|---|
| Financial revision bump | c34efb40 | `RecurringRoute.kt` | `LaunchedEffect(financialDataRevision)` refresh + restore | 41–46 |
| Last admitted session | c34efb40 | `RecurringPeriodPaymentSession.kt` | `sessions.values.lastOrNull { it.admitted }` | 144 |
| Queue refresh | c34efb40 | `RecurringOccurrenceViewModel.kt` | `acceptQueue` → `refresh` on Done | 230–236 |
| Binding change reset | c34efb40 | `RecurringOccurrenceViewModel.kt` | `periodPayment.clear()` on binding change | 82–85 |
| Connected journey test | — | `RecurringPaymentJourneyRouteTest.kt` | **absent on AUDIT_BASE** | only on #405 tree |

**PROPOSED:** Port journey test **intent** from `c0279d86:android/.../RecurringPaymentJourneyRouteTest.kt` (create→pay→return→link), not stale fixtures.

---

## Unresolved edges (explicit)

1. **B01/B02 create foreign currency** — main lacks UI; fix isolated on #415 `14c9eca8` (8 files). Do not treat #415 as merged.
2. **B04/B05 `_recurring_payment_prefill`** — `#405` only; not carried by #412/#414. Merchant/amount on “记录本期付款” depend on user re-entry on main.
3. **B05/B10 `return_payment_expense_id`** — missing from `ExpenseReturnContext` and draft fields on main.
4. **B06/B02 unknown series currency at payment** — `RecurringOccurrenceHost` gate (line 55) suppresses entire manual sheet; #405 expected explicit currency pick.
5. **B08/B10 `preferredExpenseId`** — `#405` Android cross-month locate; not on AUDIT_BASE.
6. **B12 reject return** — `web_reject` hardcodes pending; #405 preserved recurring origin on ignore.
7. **B13 E2E producer** — `RecurringPaymentJourneyRouteTest.kt` not on main; `RecurringOccurrenceRoomContinuityTest.kt` covers partial Room continuity only.
8. **Payment journey contract file** — `TICKETBOX_RECURRING_PAYMENT_JOURNEY_CONTRACT.md` exists at `c0279d86` only; AUDIT_BASE uses occurrence contract + #412 tests.
9. **Gmail three final contracts** — no session entry (BLK-GMAIL); scan used repo contracts only.

---

## Shared subchains (reference)

**S-B-LINK** — explicit occurrence association:  
`recurring_occurrence.html` / `RecurringOccurrenceSheet` → `set_occurrence_payment` / `RecurringOccurrenceDispatcher` → `occurrence_response` → reserve recompute.

**S-B-PAY** — period payment without fulfillment:  
`record_payment_href` or `recordPeriodPayment` → `create_manual_expense` / `createManualExpense` → pending expense → FX/confirm → return via `confirm_return_redirect` / `restoreAdmittedPeriodOccurrence` — **no** `set_occurrence_payment` until user links.

---

*Scan status: B01–B13 source TRACED on AUDIT_BASE with contrast notes. No runtime verification in this artifact.*
