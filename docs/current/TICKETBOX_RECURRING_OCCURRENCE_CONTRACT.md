# Monthly recurring occurrence working product contract

Status: candidate qualified and merged in #373; independent merged-main qualification pending.
Decision date: 2026-09-06. Source base: `1d5cc293a94dd7e9b13fdf2a5442d505907d7d3b`.

This is the maintained task contract for this vertical slice. Its authority is the
current Goal's explicit delegation of product design and implementation to Codex,
and the Owner's September 6 ruling to complete system capabilities before polish.
It implements Product contract §6.5 and post-G2 Gate P1's Series/Occurrence promise.
It does not replace the three original contracts or reopen Windows lifecycle HOLD.

## Problem and user outcome

A household member records monthly rent, confirms its payment, and needs to know
which obligations remain. At the source base the recurring registry stores a monthly baseline
and a reminder date but no period fulfillment. The discretionary calculation
subtracts both every active baseline and every confirmed expense. The same bill
can occupy the calculation twice; payment cannot advance its reminder.

The user will open a recurring item, choose a month, and explicitly associate an
existing confirmed expense that fully satisfies that month's obligation. They
can inspect the payment and undo a mistaken association. Web and Android use the
same Planning command/query owner. No expense is created or changed by this action.

## Decisions and boundaries

| Meaning | Classification and basis | Decision |
| --- | --- | --- |
| Series and occurrence are distinct | Contract inference: Product §6.5 / Gate P1 | Existing `RecurringItem` remains the monthly series. An occurrence is identified by ledger, series public ID and explicit `YYYY-MM` period. |
| Payment authority | Contract inference: FinancialFacts and suggestions boundaries | Only the user associates a canonical confirmed expense. Merchant/amount similarity may help find it; it never proves fulfillment. |
| Full fulfillment | Ordinary reversible product policy, delegated in Goal | One whole expense satisfies one monthly obligation. Its amount may differ from the baseline. The action clearly says it marks that month's bill paid. A payment cannot satisfy two occurrences. Partial allocation, split payments and non-monthly cadence are outside this first complete task. |
| Financial preservation | Contract invariant | Linking/unlinking writes only Planning associations and their revision history, never expense amount, currency, accounting time, offsets or confirmation. |
| Corrections | Ordinary reversible product policy | The association follows the same expense identity and its current confirmed amount. Rejection or active reversal makes fulfillment require review and restores the reservation. Refunds remain actual offset facts and do not silently undo the user's bill association. |
| Period and reminder | Ordinary reversible product policy | The user chooses the obligation month; payment accounting month is preserved independently. The stored expected date remains the editable schedule anchor. The next reminder is a derived date that skips explicitly fulfilled months, preserving the anchor day and clamping at month end. Clearing the anchor disables reminders. |
| Planning estimate | Contract inference and ordinary presentation policy | Remaining planning capacity uses planned income, actual confirmed spending, and outstanding recurring reservations. It is an estimate, never an actual bank balance or proof that income arrived. Monthly fixed baseline summaries retain their separate meaning. |
| History | Ordinary reversible product policy | Occurrence association revisions preserve actor, period, old/new payment identity and command identity. Clearing leaves its OCC revision intact. No migration invents historical paid occurrences from merchant observations. |

Alternatives rejected: merchant auto-matching would invent fulfillment authority;
subtracting all confirmed expenses from the fixed baseline would confuse unrelated
spending; marking paid without a canonical payment would make reconciliation
unverifiable. Leaving the duplicate reservation preserves the current user failure.
The chosen association is reversible and uses existing financial facts. It adds no
new financial posting, consent, secret, host mutation or destructive data policy.

## Complete task and failure behavior

1. A reader opens a recurring item and selected month. The page shows the monthly
   plan, unresolved or fulfilled state, associated payment if present, and reminder.
2. A writer selects a confirmed expense from the same ledger and explicitly
   confirms full fulfillment. The request freezes the period, expense identity and
   expense revision, occurrence OCC token, series revision and idempotency key.
3. The command claims idempotency before OCC, validates the same ledger and current
   writer/currency capability, serializes the series and selected payment, writes
   the association and audit revision, and commits with its stable command result.
4. Duplicate/unknown-result retries retain the original key and payload. A stale
   series, occurrence or selected expense is rejected without silent rebasing. An
   already used payment, rejected/reversed payment, or archived series is refused.
5. Android publishes this reversible association intent to the existing Room queue
   before network dispatch. Existing principal/dataset binding, serial targeting,
   conflict/quarantine and retry rules apply. Pending does not mean paid.
6. Web preserves the original form and command identity on recoverable failures;
   conflicts explain the need to refresh/review. Viewer controls are read-only and
   backend authorization remains decisive.
7. Undo clears the association under the same OCC/idempotency contract. It does not
   undo the actual payment. The reservation and reminder are recomputed.

No automatic schedule row generation, generic workflow engine or second expense
writer is introduced. Query-only unresolved periods need no database insert.
Existing create/edit/pause/archive/restore and observation provenance remain.

## Consumer and retirement map

- Backend: recurring command/query owner; canonical expense eligibility; monthly
  outstanding reservation reader; existing budget discretionary API and Web page.
- Web: recurring list to month fulfillment, confirmed payment selection, result,
  error/undo, and links to the canonical expense; local authentication and CSRF.
- Android: recurring item to fulfillment, existing API/DTO/repository/Room command
  protocol, pending/conflict states, result refresh and notification date consumer.
- Budget baseline summaries still show the monthly plan. Only calculation legs
  promising *remaining* capacity consume outstanding reservations.
- Retire the active-baseline-as-unpaid calculation at every affected consumer and
  the raw schedule-anchor-as-next-reminder consumer. No dual calculation owner.

## Evidence and stop conditions

The first falsifier uses synthetic planned income 1000, rent baseline 100 and one
confirmed rent payment 100. After explicit fulfillment, remaining planned capacity
is 900, with actual spending 100 and outstanding rent 0. An unrelated same-merchant
expense must not fulfill it automatically. Undo restores rent's unresolved state;
the actual expense remains unchanged. The next due date advances only after the
explicit association and returns when the association becomes invalid or is undone.

Gate map: smallest route-level PostgreSQL RED; command success/replay/OCC/tenant/
role and reversal/undo regression; real Web form journey; Android enqueue/recovery
and connected user journey; migration metadata/readiness; bounded exact-snapshot
review; exact final candidate CI/CodeQL/Connected, then independent main runs.
Use existing cloud lanes for PostgreSQL and Android; no local heavy suites.

Hypothesis: explicit association makes the plan-to-payment relationship understandable
and removes double reservation without inventing facts. Mechanism qualification is
not customer validation. Owner Internal Beta will determine whether single-payment
fulfillment covers the recurring tasks actually used. Revisit this contract if a
representative task requires split/partial payments; do not emulate them by changing
financial amounts. Stop this slice when its task and gates pass. Retain income
projection history, Backstage capability findings and other system gaps in the
Atlas, then continue the original Goal. This slice cannot complete the full RC.

## Current evidence (not release acceptance)

- Test-only `5c7560b2` reproduced the missing occurrence route on cloud PostgreSQL:
  CI `34004587739`, ordinary 2/2, confirmed payment followed by occurrence GET 404.
- `ce293ece` passed ordinary 2/2 including explicit link, stable replay, undo,
  correction to zero, reversal, cross-ledger/role and the real Web form journey;
  all real-db shards and the Windows installer build also passed. Its full CI
  failed on an explicit-scope static guard, Android copy/structure checks, a missing
  required button icon, and a Desktop Node probe timeout. It is not a qualified candidate.
- Bounded read-only reviews of `8c717248` backend and `ce293ece` Android retained
  three concrete fixes: canonical confirmed zero amounts remain eligible; the
  associated payment has a real detail entry; original submissions are identifiable
  and recoverable without a successful period GET. Snapshot manifests matched.
- Final candidate `c50519b2548efd737c8ce2e7fa0fb0bd3363af26` passed CI `34009632568`,
  CodeQL `34009632598` and actual Connected `34009632572` (111 emulator tests,
  no failures or skips). The tested PR merge and candidate share tree
  `7a60709583b532fd8f90f0d1bb6f042d0721ce13`.
- Protected squash merge #373 produced `3f604d1d0ba7c34afef1311c963c817431a2c521`
  with that same tree. Its independent CI `34010262230`, CodeQL `34010262245`
  and Connected `34010262247` are running at this evidence update.
- Room close/reopen and synthetic response-loss probes are mechanism tests, not
  process-death, cross-client, clean-Windows or full Internal Beta qualification.
