# Currency choice and correction

Authority: the full Goal and the user's 2026-09-08 report that CNY was selected
and locked without a choice; the final product contract assigns money meaning to
persisted currency facts, explicitly excluding environment defaults. Codex owns
product design and implementation under that delegation. Executing changes to
the user's existing financial data remains a separate, concrete approval step.

## Required user outcome

- A fresh installation asks its installation Owner to choose a home currency.
  No currency is preselected, and no financial writer makes the choice. Setup
  remains reachable before money pages can render amounts. The existing paired
  Desktop Owner entry and activation command are reused.
- The confirmed persisted choice drives parsing, storage, FX and presentation.
  An environment fallback must neither select currency nor veto the choice.
- An already implicit binding needs a correction path, including installations
  with existing records. Protect original amounts, currencies, snapshots and
  relationships; a global relabel or automatic guessed conversion is forbidden.
  The absence of such a path is a product gap, not an immutable-data justification.
- A changed binding must not reinterpret or settle old offline intent. Clients
  retain original intent and explain the required continuation. Existing stable
  receipts stay stable across retries.

## Impact before construction

| Responsibility | Actual entries / consumers and direct proof |
|---|---|
| Choice and identity | `web_currency_adoption`, Desktop bridge/session and installation Owner claim; `test_currency_adoption_product` |
| Authority and old success exit | `currency_binding_service` first-fact claim, env match, runtime projection and legacy debt envelope; `test_currency_binding_capability`, `test_currency_binding_marker`, runtime compatibility tests |
| Money writers | Expense/manual/OCR/import, debt/repayment/proposal, split invitation, budget/goal/income/recurring/category rules; existing command and currency/FX tests, DB writer fences |
| Parsing and FX | `currency_common`, `exchange_rate_service`, `fx_rate_provider`, scheduler; explicit source/home arguments must replace env-derived meaning, including pure-helper callers |
| Persistence and recovery | Binding/audit/idempotency receipt, currency evidence inventory and SQL guards; migration tests; Android negotiated binding, queued payloads, dispatcher recovery and legacy gate |
| Debt create intent | Web form and Android `DebtCreationRepository` capture currency; `CreateDebtDispatcher` maps the durable v1 intent to the wire request without replacing its meaning. `debt_command_service` owns create/replay; an old completed receipt is reusable only when its original request and persisted currency match. Request-contract, API replay and existing Room-payload tests verify these boundaries |
| Changed command protocol | Debt create and manual FX reuse the income command's version dependency before body validation. Old clients receive `client_upgrade_required`; runtime projection no longer promises unversioned write compatibility. Direct HTTP producers negotiate through the existing test client helper; protocol refusal tests use the original old request shape |
| All monetary HTTP writers | `resolve_write_capability` rejects unversioned clients for every currency; the CNY/revision-one mode and its old success exit are retired. Web/Owner/upload-link and internal jobs retain their existing server identity. Ordinary test app/rotated/member-token producers declare current persisted negotiation, legacy tests retain raw authentication, and the live smoke client reads runtime compatibility before sending app requests |
| Expense currency continuation | Pending FX refresh, date/original-currency edits and manual pending FX preserve `Expense.home_currency_code`. The shared payload owner requires explicit context; new manual/notification capture still uses the confirmed default. Direct conversion/refresh tests verify record meaning under a different default |
| CSV money continuation | Explicit file currency is captured per row through parsing, durable staging, API/Web preview, paged application and receipt replay. The old current-default relabelling exit is retired. Migration uses a linked expense or persisted ACTIVE binding; unknown history waits for Owner adoption. Pure parser, API/Web/paged retry, FX-pair and real migration tests are the direct producers |
| Income money continuation | API/Web create and Android drafts capture currency; the plan/version owns ordinary edits and durable v1 replay without changing the old update fingerprint. Plan/revision migration, audited adoption, receipt reconciliation, API/Web editing, Android list/editor/overview, recycle bin and advisor projections use the recorded meaning. Income query replaces the Android debt-list currency bridge. Direct command/ORM/form/DTO/Room producers and mixed-currency/refusal tests are migrated; cloud qualification is pending |
| Product consumers | Money pages, recycle bin and Owner projections, reports/insights, Android forms/caches and sync feedback, Desktop first-use navigation; real non-CNY choice then financial task, refusal/replay and cross-client recovery |
| Budget money and save (in construction) | API PUT and Web use one captured-currency/OCC/idempotent save owner; the unversioned upsert is retired. Categories inherit the existing composite-FK parent. Migration/adoption preserve amounts and versions; archive/restore retain that carrier. Web currency conflicts preserve raw input and offer a separate current editor. Android captures the budget response. The existing Budget facade delegates original-command enqueue/observation/recovery to BudgetSaveRepository; SaveMonthlyBudgetDispatcher remains the sole sender. Room rows, binding checks, keys and receipts stay unchanged. Its debt-list bridge and direct HTTP writer are retired. Budget/overview, Backstage, recycle and Android notifications use recorded currency. Both global sync entrances now require the same command recovery owner and show the original money; unsupported intentions cannot offer retry, currency mismatch requires review, and HTTP 404 preserves the original. Stop confirmation promises no server undo. ViewModel replay/refusal and global UI tests cover these consumers; device/cloud qualification and direct navigation from global recovery to the matching budget month remain open |
| Budget aggregation and remaining consumers | Confirmed expense/refund streams now carry recorded currency; budget projections and income share a read-only FX helper. Missing conversion stays unknown. Period reports, spending goals and advisor spending readers still need their common-currency projection. Recurring amounts still require their captured-currency migration; a non-native budget cannot present that legacy fixed total as its own currency. Nonempty default changes remain unavailable until these consumers close |
| Legacy Android budget authority (retirement candidate) | Removed the unused Settings writer, preference accessors, expense facades and untyped statistics fallback; stored user bytes remain untouched. Statistics now query the Budget owner using the full logical binding, clear cached results on identity replacement and refresh after confirmed fact changes. Settings/Stats producers migrate; same-named-ledger replacement and navigation during pending reads have direct regressions. Cloud qualification remains open |
| Android budget drafts (candidate) | Plan hub and budget detail use the Budget factory with Android saved state. Raw drafts retain their original currency/version per full binding and month. Room takes ownership after enqueue; restored drafts reconcile against the original queued command without resubmission, and unrelated completed edits cannot erase newer input. Recovery tests cover month/identity changes, reconstruction and queue transfer; device continuation remains open. This does not claim force-stop persistence for never-submitted input |
| Verification producers | Explicit currency fixtures for ordinary and migration tests; legacy bootstrap/admin HTTP smoke and Desktop bridge tests declare a configured CNY baseline. Dedicated fresh Owner product tests and VM prove actual initial selection. Generated API and protocol gates follow real semantic changes |

This inventory defines the affected scope, not an assertion that each path is
already repaired. Unknown consumers cannot be omitted as unaffected.

## Correction decision

The installation's current choice supplies the default for new entry and the
reporting currency. It must not remain the interpreter of every historical
integer. Changing that choice preserves records, original/home currency and FX
snapshots, relationships, immutable revisions and stable command receipts.

Before enabling changes on a nonempty installation, money rows that lack a
currency carrier must acquire their existing persisted meaning: budgets and
categories, spending goals, income plans and revisions, recurring items, amount
rules, staged imports and manual FX rates. Children may inherit a frozen parent
currency only where the actual relationship guarantees it. The old binding is
migration evidence, never a guess from the environment. Read models aggregate
only a common currency through the existing FX owner, with missing conversions
visible; they must not relabel or add unlike units.

Changing the default and correcting an incorrectly recorded historical currency
are distinct user actions. Historical corrections reuse the domain's command
and revision owner, with a reviewable before/after result. An accepted offline
command keeps its own money currency; transport negotiation cannot replace it.
Legacy intents whose meaning cannot be established remain recoverable, and an
uncertain prior submission requires receipt reconciliation before resubmission.

## Construction and exit

First prove absent choice and non-CNY selection against the current default;
retire implicit activation and configuration-as-money-authority with all direct
consumers. Then close existing implicit-binding correction, using actual evidence
to distinguish empty setup from records that require preserved historical meaning.
Manual rates now capture both currencies in their command, stored row and
lookup. The migration uses an existing ACTIVE binding; unknown legacy targets
wait for the same audited Owner adoption transaction. Expenses, offsets and
repayments request rates for their explicit money context. This is a candidate
implementation; the other money carriers, nonempty choice transaction and
offline continuation remain unfinished in this delivery package.
Debt creation now carries its captured currency through Web and the durable
Android v1 queue; repayment/proposal/bill-split children use their parent's
frozen currency. Web validation keeps the form currency and retry key; a changed
already-used form requires a nonwriting review before a new command. These
changes are candidates awaiting full qualification, not closure of all money
consumers or permission to change an existing installation default yet.
Expense FX refresh and date/currency corrections now pass the stored record
currency to the same FX owner. Direct and staged imports retain each row's parse
currency, including mixed-currency files and later retries. Planning carriers
still need completion. The old CNY
unversioned-writer exception is now removed across the monetary owner and its
direct client/test producers are migrated; current cloud qualification is pending.

Income creation still needs accepted-response-loss reconciliation and Web raw-form
retention; it currently has no creation idempotency key. Missing-FX recovery in
advisor/insight consumers and the remaining planning currencies must also close
before the nonempty default-change command can be delivered.

Qualification includes TDD, exact candidate cloud gates, bounded review, real
Desktop/Android continuation and independent main qualification. No long local
suite or Windows lifecycle expansion. Neither initial-choice work alone nor this
contract closes the currency package or the full Goal.
