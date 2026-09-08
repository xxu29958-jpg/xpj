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
| Product consumers | Money pages, recycle bin and Owner projections, reports/insights, Android forms/caches and sync feedback, Desktop first-use navigation; real non-CNY choice then financial task, refusal/replay and cross-client recovery |
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

Qualification includes TDD, exact candidate cloud gates, bounded review, real
Desktop/Android continuation and independent main qualification. No long local
suite or Windows lifecycle expansion. Neither initial-choice work alone nor this
contract closes the currency package or the full Goal.
