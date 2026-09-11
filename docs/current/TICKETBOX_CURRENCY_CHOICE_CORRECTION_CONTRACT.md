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
| Budget inputs and manual rates | API read, Web advice/monthly report and Android advice use common-currency projections; missing source/date/rates stay unknown and block paid generation. The complete private advice basis contributes a read-only fingerprint to existing cache freshness, including cross-client historical-rate changes. Manual rate creation/correction has one OCC/idempotent owner and original receipt; Web retains the task and Android uses the existing Outbox and both sync entries. Original pair/date/month/home/key/version survive recovery. Retired: blind rate upsert, raw budget-input sums and unused personal/spent readers. Direct proof: projection/HTTP/CSRF/form/receipt tests, rate-version migration, Android DTO/owner/cache/Route/Room. |
| Persistence and recovery | Binding/audit/idempotency receipt, currency evidence inventory and SQL guards; migration tests; Android negotiated binding, queued payloads, dispatcher recovery and legacy gate |
| Debt create intent | Web form and Android `DebtCreationRepository` capture currency; `CreateDebtDispatcher` maps the durable v1 intent to the wire request without replacing its meaning. `debt_command_service` owns create/replay; an old completed receipt is reusable only when its original request and persisted currency match. Request-contract, API replay and existing Room-payload tests verify these boundaries |
| Changed command protocol | Debt create, manual FX, goal create/edit and recurring create/candidate/edit reuse the income command's version dependency before body validation. Old clients receive `client_upgrade_required`; runtime projection no longer promises unversioned write compatibility. Direct HTTP producers negotiate through the existing test client helper; protocol refusal tests use the original old request shape |
| All monetary HTTP writers | `resolve_write_capability` rejects unversioned clients for every currency; the CNY/revision-one mode and its old success exit are retired. Web/Owner/upload-link and internal jobs retain their existing server identity. Ordinary test app/rotated/member-token producers declare current persisted negotiation, legacy tests retain raw authentication, and the live smoke client reads runtime compatibility before sending app requests |
| Expense currency continuation | Pending FX refresh, date/original-currency edits and manual pending FX preserve `Expense.home_currency_code`. Frozen amount corrections retain the recorded home and rate under a different default while still checking current write permission/protocol. The shared payload owner requires explicit context; new manual/notification capture still uses the confirmed default. Direct conversion/refresh/correction and receipt tests verify these boundaries |
| CSV money continuation | Explicit file currency is captured per row through parsing, durable staging, API/Web preview, paged application and receipt replay. The old current-default relabelling exit is retired. Migration uses a linked expense or persisted ACTIVE binding; unknown history waits for Owner adoption. Pure parser, API/Web/paged retry, FX-pair and real migration tests are the direct producers |
| Income money continuation | API/Web create and Android drafts capture currency and server month. Create commits the plan, first revision and original receipt together; edit retains its v1 fingerprint. One Android submission owner handles create/edit, exact-row navigation and both global recovery entries. Web refusal retains raw fields and the original key. Plan/revision adoption, list/editor/overview, recycle bin and advisor projections use recorded meaning; the debt-list currency bridge and HTTP-first create exit are retired. Direct command/ORM/form/DTO/Room producers are migrated |
| Product consumers | Money pages, recycle bin and Owner projections, reports/insights, Android forms/caches and sync feedback, Desktop first-use navigation. Goal/rule/recurring/income original Web forms share one ledger check before object lookup, writing or rekeying; switching ledger preserves their raw fields for an explicit return. Direct handler and native CSRF-form tests cover refusal and unchanged resubmission. Remaining cross-client recovery stays in RC delivery |
| Budget money and save | API PUT and Web use one captured-currency/OCC/idempotent save owner; the unversioned upsert is retired. Categories inherit the existing composite-FK parent. Migration/adoption preserve amounts and versions; archive/restore retain that carrier. Web currency conflicts preserve raw input and offer a separate current editor. Android captures the budget response. The existing Budget facade delegates original-command enqueue/observation/recovery to BudgetSaveRepository; SaveMonthlyBudgetDispatcher remains the sole sender. Room rows, binding checks, keys and receipts stay unchanged. Its debt-list bridge and direct HTTP writer are retired. Budget/overview, Backstage, recycle and Android notifications use recorded currency. Both global sync entrances now require the same command recovery owner and show the original money; unsupported intentions cannot offer retry, currency mismatch requires review, and HTTP 404 preserves the original. Stop confirmation promises no server undo. Both entrances can open the original month through the existing Budget route and factory; navigation and editor restoration share one saved month. ViewModel replay/refusal and global UI tests cover these consumers and await durable outcomes rather than virtual Main advancement. |
| Monthly/lifestyle and overview | Stats, Reports and Web overview/calendar/page subtotals share the projected confirmed-stream reader. Offset dates/currencies and inherited tags remain intact. Missing amounts stay unknown; counts and scores remain available. Android caches the server response by full binding/month/tag/currency/timezone, labels its age and rejects late responses from another task. Expense-cache mapping rejects missing recorded currencies before any batch replacement. Retired: raw aggregate fallbacks, duplicate Reports reader, unused 14-day trend and unused Android insight producers. Direct proof: projection/router/template/chart, DTO/cache/VM and Room/Route producers |
| Ledger list | Total/day headers group signed stream contributions by each root or offset's recorded currency; unknown amounts remain unavailable. Shared display handles both headers and original rows without ambient CNY fallback. Retired: mixed raw totals and folded-preview amount ordering. Grouping, actual Compose consumers and correction/Room continuity producers cover the change |
| Default change | The existing paired Desktop installation Owner entry changes new-entry/report defaults through one OCC/idempotent command and audit transaction. Original receipts retain before/after currency and confirmation time; history, initial adoption evidence and queued commands remain unchanged. SQL transition guard and manifest migrate together. Native error/review keeps raw input and original key; current settings are read separately. Direct proof: owner/concurrency/receipt/migration, real Form/CSRF/claim and paired Desktop producers |
| Manual draft currency | Web and Android capture original payment and home currency when a task begins; new tasks refresh the default, old raw input and submitted bodies retain their meaning. Existing manual command owns insertion; complete legacy original-money requests retain their wire semantics, while ambiguous bare amounts refuse new writes and accepted original keys can still recover. Both sync entries hide impossible retries for unverifiable legacy money, and retry execution checks the current Room refusal without changing stored bytes. Browser draft storage, Android mapper/dispatcher and real Room/transport producers are migrated; implicit CNY fallback is retired. Manual admission and receipt continuation subsequently closed in #398 |
| Historical fact display | Web revisions format each before/after snapshot using its own currency; missing historical carriers stay unknown. Item/split editors and read views use the parent record currency, and sent invitations use their own recorded currency. Retired: runtime-default timeline arguments and mixed-symbol invitation presentation. Snapshot, template and split-invitation producers verify these consumers; historical FX continuation remains open |
| Remaining currency work | Historical currency correction remains active; manual admission/original receipts closed in #398. Repayment notification capture currently supports CNY only and has no durable Outbox; refusal cannot promise retained offline intent. Unused helpers do not prove a working insight entry |
| Period reports | One projected confirmed stream supplies current/previous/year-over-year totals, category/merchant rankings, trend, CSV, six-month budget history and largest-expense links. Missing money remains nullable; count tasks remain available. Web and Android preserve the original report currency/month/filters through fact and manual-FX continuation. Retired: raw monetary ranking and duplicate largest-expense reader. Direct proof: mixed-currency ordering, partial comparisons, offsets/aliases, CSV, actual Web template/chart/form return and Android report/export/recovery producers. |
| Recurring money | Backend/Web commands capture currency and retain accepted manual receipts; migration/adoption preserve amounts, versions and relationships. Candidates, anomalies, budget/advisor reservations and overview reuse the existing FX owner; unavailable conversion stays unknown. Android saves persist before transport and retain original keys/OCC/currency; recorded views use their own units and totals remain separated by currency. Direct HTTP/Synced exits, mixed raw totals and unused display-default arguments are retired. Backend currency groups passed; Android continuation is integrated. |
| Recurring Android continuation | Entries: recurring record/editor/period sheet, Plan, obligation sync and Settings sync. Existing recurring repositories own admission, summaries and recovery; Outbox alone persists/dispatches. Both sync factories and stop dialogs retain the original context. Occurrence revision 2 captures payment currency; revision 1 keeps its association/key/versions and displays its unproven currency as unknown without rewriting stored JSON. Plan/paid amounts use separate recorded currencies; unexpected receipts remain unresolved. Page/global recovery now share one owner and retry eligibility. Direct producers: DTO/dispatcher/repository/global-policy tests and Connected editor/JPY payment/Room-restart/UI tests. |
| Spending goals | API/Web and Android create/edit use captured currency and original accepted receipts; the existing Outbox owns Android publication/recovery. List/detail/statistics, Web overview/search/recycle and both sync entrances consume record or original-intent currency. Missing FX leaves progress unknown. Retired exits: runtime currency overlays, raw mixed-currency sums, latest-row update replay and direct Android create HTTP. Persistence: goal column/guard, migration/adoption/evidence/manifest, request/response DTOs, original Room payload/key/OCC and retained Web forms. Direct proof: request/response and shared FX tests; API create/update replay/OCC, migration and adoption; Web refusal and secondary-consumer tests; Android owner/dispatcher/VM and Connected original-money/reopen tests. Debt-clearance goals remain nonmonetary and retain linked-debt currency evaluation. |
| Amount rules | Existing rules capture their own currency; migration/adoption preserve thresholds and versions. Automatic classification and bulk preview/apply share the existing FX reader: an unavailable comparison retains the category and stops lower-priority matching. Preview consent and audit use captured inputs/results. Web and Android expose amount editing and preserve original submissions; create/update receipts and the existing Outbox own retry. Retired exits: raw cross-currency comparisons, current-default formatting, latest-row replay, HTTP-first writes and generic rule recovery. Direct proof covers schema/migration, matching/preview/OCC/audit, Web forms/toggle/replay, Android DTO/owner/Room and both sync entrances. Metadata-only rules remain usable without monetary adoption; delete/restore and category rollback retain their existing owners. |
| Legacy Android budget authority | Removed the unused Settings writer, preference accessors, expense facades and untyped statistics fallback; stored user bytes remain untouched. Statistics now query the Budget owner using the full logical binding, clear cached results on identity replacement and refresh after confirmed fact changes. Settings/Stats producers migrate; same-named-ledger replacement and navigation during pending reads have direct regressions. |
| Android budget drafts | Plan hub and budget detail use the Budget factory with Android saved state. Raw drafts retain their original currency/version per full binding and month. Room takes ownership after enqueue; restored drafts reconcile against the original queued command without resubmission, and unrelated completed edits cannot erase newer input. Recovery tests cover month/identity changes, reconstruction and queue transfer. This does not claim force-stop persistence for never-submitted input |
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

#397 is CLOSED: explicit initial choice, changeable defaults and the captured
money consumers above are integrated and independently main-qualified. The
impact inventory records affected responsibilities and direct producers. Exact
source and qualification
are linked from [PR #397](https://github.com/xxu29958-jpg/xpj/pull/397) and the
subsequent [integrated-main qualification](https://github.com/xxu29958-jpg/xpj/pull/398).

[Manual creation continuity](TICKETBOX_MANUAL_CREATION_CONTINUITY_CONTRACT.md)
then retired HTTP-first admission and latest-row replay in #398, also CLOSED and
main-qualified. Original forms, currencies, intent bodies, keys and accepted
receipts retain their meanings across default changes and recovery.

Historical FX correction continuation remains a separate active journey; a
green default-change check does not close it. Repayment notification capture
still supports CNY only and does not have durable Outbox admission, so a refusal
cannot promise retained offline intent. Full cross-client interruption, remaining
consumer delivery and exact Internal Beta RC qualification are still required.

These results do not authorize changes to the user's existing financial data.
No long local suite or Windows lifecycle expansion is part of this slice.
