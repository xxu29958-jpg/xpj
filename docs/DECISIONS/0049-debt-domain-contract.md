# ADR 0049: Debt Domain Contract

Status: Accepted (Target Contract; Runtime Subset)
Date: 2026-06-14
Type: Domain Contract
Lineage: replaces the earlier financial-domain wording and consolidates the retired early drafts `0049-debt-and-liability-tracking` and `0050-event-store-schema-and-migration`.

---

# 0. Scope

This ADR defines one new financial domain:

> Debt = a frozen obligation plus append-only repayment/correction facts

The prior A/B split is intentionally removed:

- "family member owes family member" is `Debt(counterparty_type=member, source_type=bill_split|manual)`
- "I owe a credit card / loan / outside person" is `Debt(counterparty_type=external, source_type=manual)`

They are the same domain. Only counterparty and source differ.

This ADR does NOT re-define foundations already owned elsewhere:

- money uses integer minor units: [[0001]]
- family ledger roles and account privacy: [[0022]]
- backend-authoritative FX snapshots: [[0027]]
- bill split invitation privacy and accept snapshot: [[0029]]
- optimistic concurrency and undo/correction discipline: [[0038]]
- PostgreSQL + `row_version` CAS: [[0041]]
- request idempotency keys for outbox-routed mutations: [[0042]]
- mascot is presentation, not business truth: [[0048]]

This ADR only defines the new Debt obligation layer, how bill split acceptance can create Debt, and how debt repayment goals and mascot transitions read Debt state.

## 0.1 Current Runtime Boundary

Current runtime already has:

- `BillSplitInvitation` accept/reject/cancel/expire from [[0029]]
- accepted receiver-side expense creation
- `income_plan` as budget/advisor input
- `spending_limit` goals
- mascot UI state machine

Current runtime does NOT yet expose:

- `Debt`
- `Repayment`
- `DebtAdjustment`
- `RepaymentVoid`
- `debt_repayment` goal evaluator
- Debt transition mascot dedupe markers

Therefore this ADR is a target contract. Confirmation checks are required before exposing the corresponding Debt features; they are not claims that the current runtime already implements them.

Slice 4 wires bill-split → Debt creation (§4) behind the `DEBT_ROLLOUT_ENABLED` flag, default OFF. A bill-split member Debt is owned by the receiver's ledger with the sender as creditor. Slice 4's hard boundary was: this flag MUST NOT be enabled until account-scoped participant confirm/reject (§5.2) is implemented, because ledger-scoped confirm/reject left a creditor who is not a member of the receiver's ledger unable to confirm or clear it.

Slice 5 implements that account-scoped participant confirm/reject (§5.2): the repayment-proposal flow now resolves a Debt by participant identity (debtor OR creditor account) unioned with ledger membership, so the cross-ledger creditor can confirm/reject/clear the obligation, and a participant-but-not-member view is redacted to the Debt shell only (no counterparty ledger internals). **The §0.1 hard-boundary prerequisite is therefore met.**

**Slice ⑤b flips `DEBT_ROLLOUT_ENABLED` to default ON (2026-06-19).** Every prerequisite for a non-broken end-to-end loop now holds: §5.2 account-scoped confirm/reject (slice 5); the cross-ledger creditor *discovery* UX shipped read-only on all three surfaces (`GET /api/debts/receivables` + `/web/receivables` + the Android Receivables screen, slice ⑤c); the cross-ledger creditor *confirm/reject* path shipped in the Android app (receivables row → cross-ledger debt detail → proposal inbox, slice ⑤b-2); and pre-rollout backfill (§4) self-heals splits accepted during the closed period via the flag-gated startup reconcile (P3b, slice ⑤a). The flag remains as a per-install opt-out (`DEBT_ROLLOUT_ENABLED=false`), forward-only per §4 — flipping it OFF for an install stops *new* bill-split Debt creation but does not remove Debts already created.

---

# 1. Existing Foundation Reuse

Debt implementation MUST reuse existing project foundations instead of inventing parallel mechanisms.

- Authorization uses `AuthContext` plus existing `LedgerMember` roles (`owner` / `member` / `viewer`).
- Tenant isolation uses existing ledger/account scoping.
- Mutation concurrency uses `row_version` CAS from [[0041]].
- Outbox-routed writes use `Idempotency-Key` from [[0042]].
- Bill split source data uses `BillSplitInvitation` frozen fields from [[0029]].
- FX and home-currency amounts use backend-authoritative snapshots from [[0027]].
- Audit/correction behavior follows append-only correction discipline from [[0038]].

0049 MUST NOT introduce:

- a second idempotency system
- a second role/relationship model
- a second FX authority
- a second settlement/netting subsystem
- mutable "already paid" or "remaining" columns as financial truth

---

# 2. Debt Model

`Debt` represents one obligation.

Required fields:

- `debt_id` / `public_id`
- `ledger_id`
- `owner_account_id`
- `direction`: `i_owe` / `owed_to_me` from `owner_account_id`'s perspective
- `counterparty_type`: `member` / `external`
- `counterparty_account_id` when `counterparty_type=member`
- `counterparty_label` when `counterparty_type=external`
- `principal_amount_cents`
- `home_currency_code`
- optional original-currency provenance fields
- `status`: `open` / `cleared` / `voided`
- `source_type`: `manual` / `bill_split`
- `source_id`
- `created_by_account_id`
- `created_at`
- `updated_at`
- `row_version`

Rules:

- Principal is frozen at creation.
- Principal MUST NOT be edited in place.
- `remaining_amount_cents` is derived, not stored as truth.
- `paid_amount_cents` is derived, not stored as truth.
- `status=cleared` is a lifecycle latch reached by transition, not an independently editable balance.
- `status=voided` requires an append-only void/correction fact; direct row mutation is forbidden.

For a debt:

```text
remaining =
  principal_amount_cents
+ sum(non-voided DebtAdjustment.amount_cents)
- sum(non-voided Repayment.amount_cents)
```

Debt is cleared when `remaining == 0`.

Debt overpayment is rejected in v1. No Debt operation may silently clamp, create credit balance, or flip direction. Live revolving credit-card balances, interest accrual, credit balances, and full balance-sheet semantics are out of scope for this ADR.

## 2.1 Fold Serialization

`remaining` is derived, but the parent `Debt` row is still the serialization point for every fold-changing write.

The following operations MUST serialize on the parent `Debt` row in the same database transaction as the child fact insert:

- committed `Repayment`
- committed `DebtAdjustment`
- `RepaymentVoid`
- `DebtVoid`
- the `open -> cleared` or `cleared -> open` status latch that follows from those facts

Allowed implementations:

- take a row lock on `debts(debt_id)` such as `SELECT ... FOR UPDATE`, then recompute/check the fold and insert the child fact
- or issue an atomic parent CAS bump, for example `UPDATE debts SET row_version = row_version + 1, updated_at = now() WHERE debt_id = :id AND row_version = :expected`

Rules:

- The overpayment check (`remaining < 0`) MUST be evaluated inside this serialized section from authoritative facts.
- Inserting a repayment/adjustment/void child row without locking or CAS-bumping the parent `Debt.row_version` is forbidden.
- A CAS conflict is not a blind retry signal. The service MUST reread authoritative facts, recompute `remaining`, and revalidate the operation before any retry with a newer parent `row_version`.
- The parent `row_version` bump is a concurrency token only; it is not financial truth and does not make `remaining` a stored balance.
- Request idempotency still follows [[0042]]: a replay of the same committed operation returns the canonical result and MUST NOT bump the parent row again.
- Different idempotency keys for different repayment attempts are not deduplicated; they are protected only by the parent Debt serialization point.

This is the contract that makes F8 true under concurrency. Two distinct repayments that each saw `remaining=100` cannot both commit `60` unless the second writer rechecks after the first serialized write.

## 2.2 Currency and FX Semantics

All Debt fold arithmetic is in `home_currency_code` minor units.

Rules:

- `principal_amount_cents`, `Repayment.amount_cents`, and `DebtAdjustment.amount_cents` are home-currency amounts.
- Original-currency fields are provenance/display only and MUST NOT be aggregated across currencies.
- Backend-authoritative FX snapshots from [[0027]] are the only allowed source for foreign-to-home conversion.
- Clients submit original currency, original amount, and event time; they MUST NOT submit exchange rates or calculate home amounts.
- A foreign-currency Debt cannot become committed until the backend can freeze a home-currency principal snapshot, or the user records it as a home-currency Debt.
- Foreign-currency repayments are resolved using the backend FX snapshot for `paid_at`, then frozen as home-currency `amount_cents`.
- Existing Debt facts do not drift when later FX rates refresh.

External Debt v1 is home-currency authoritative fixed-principal/installment/IOU bookkeeping. If the real-world obligation is denominated in a foreign currency, the Debt still carries a frozen home principal and optional original-currency provenance. It is not a live FX liability engine.

Foreign close-out drift is expected. If paying the exact remaining original-currency amount would not sum to zero in home currency because exchange rates moved, the user must record an explicit `DebtAdjustment(reason=fx_closeout)` before or with the final repayment. The system MUST NOT silently clamp, auto-revalue principal, or treat original-currency equality as financial clearance.

---

# 3. Repayment and Correction Facts

## 3.1 Repayment

`Repayment` is append-only.

`Repayment` means a committed repayment fact. A pending "I paid" proposal for member Debt is workflow state and MUST NOT enter the repayment fold until confirmed.

Required fields:

- `repayment_id` / `public_id`
- `debt_id`
- `amount_cents`
- optional original-currency provenance fields for the payment
- `paid_at`
- `actor_account_id`
- optional `proposal_id` when committed from a member repayment proposal
- `idempotency_key`
- `created_at`

Rules:

- `amount_cents > 0`
- replays with the same idempotency key and fingerprint return the same committed repayment
- replays with mismatched fingerprint return `idempotency_key_reused`
- a repayment that would make `remaining < 0` is rejected
- repayment never mutates the Debt principal
- committing a repayment MUST serialize on the parent Debt row per §2.1

## 3.2 MemberRepaymentProposal

`MemberRepaymentProposal` is workflow state for adverse-interest member Debt. It is not a repayment fact and never enters the `remaining` fold by itself.

Required fields:

- `proposal_id` / `public_id`
- `debt_id`
- `debtor_account_id`
- `creditor_account_id`
- `proposed_by_account_id`
- `proposed_amount_cents`
- optional original-currency provenance fields for the proposed payment
- `paid_at`
- optional note/evidence reference
- `status`: `pending` / `confirmed` / `partially_confirmed` / `rejected` / `withdrawn` / `expired` / `superseded`
- optional `confirmed_amount_cents`
- optional `committed_repayment_id`
- optional `supersedes_proposal_id`
- `idempotency_key`
- `created_at`
- `expires_at`
- optional `resolved_at`
- optional `resolved_by_account_id`

Rules:

- `proposed_amount_cents > 0`.
- The default expiry is 30 days from `created_at`; expired proposals cannot be confirmed.
- Each Debt may have at most one `pending` repayment proposal at a time.
- The database MUST enforce that invariant with a partial unique index equivalent to `UNIQUE(debt_id) WHERE status='pending'`.
- Service-level supersede logic is a workflow convenience, not a substitute for the unique index. Replacement creation must name the currently pending proposal the client saw; only that exact pending proposal may be marked `superseded` while the new pending proposal is inserted in one transaction. A replacement request with no supersede target, or with a stale target after another device already created a newer pending proposal, is rejected and the partial unique index remains the concurrency backstop.
- A debtor may withdraw their own pending proposal.
- A debtor may change amount/date only by creating a new proposal that explicitly supersedes the old pending proposal; proposal amounts are not edited in place.
- A creditor may confirm the full proposal amount.
- A creditor may partially confirm a lower positive amount. Partial confirmation commits one `Repayment` for `confirmed_amount_cents`, closes the proposal as `partially_confirmed`, and does not leave the rejected remainder pending.
- A creditor may reject the proposal without committing any repayment.
- Confirmation, partial confirmation, and rejection are terminal workflow transitions.
- A proposal can be confirmed or partially confirmed only while it is the current pending proposal for that Debt.
- Confirming any amount MUST serialize on the parent Debt row per §2.1 and MUST reject overpayment after rechecking current `remaining`.
- The committed `Repayment` created from a proposal MUST link back through `proposal_id`.
- Pending, withdrawn, rejected, expired, and superseded proposals do not reduce `remaining`.

## 3.3 DebtAdjustment

`DebtAdjustment` is append-only and is the only way to correct principal-like mistakes after Debt creation.

Required fields:

- `adjustment_id` / `public_id`
- `debt_id`
- signed `amount_cents`
- reason
- `actor_account_id`
- `idempotency_key`
- `created_at`

Rules:

- reason is required
- adjustment MUST NOT make `remaining < 0`
- adjustment that increases another member's burden requires affected-party confirmation
- incorrect adjustments are corrected by another adjustment, never by rewriting history
- committing an adjustment MUST serialize on the parent Debt row per §2.1

## 3.4 RepaymentVoid

`RepaymentVoid` is append-only and is the only way to undo a mistaken repayment.

Required fields:

- `repayment_void_id` / `public_id`
- `repayment_id`
- reason
- `actor_account_id`
- `idempotency_key`
- `created_at`

Rules:

- one repayment may be voided at most once
- voiding a repayment reopens Debt if derived `remaining > 0`
- voiding a repayment MUST NOT delete the original repayment row
- voiding a repayment MUST serialize on the parent Debt row per §2.1

## 3.5 Debt Void

Voiding an entire Debt is allowed only through an append-only correction fact.

Required fields:

- `debt_void_id` / `public_id`
- `debt_id`
- reason
- `actor_account_id`
- `idempotency_key`
- `created_at`

Rules:

- bill-split-sourced Debt voiding requires the same adverse-interest confirmation rules as member Debt adjustment
- voided Debt no longer contributes to open debt totals or goals
- voided Debt remains visible in audit/history
- voiding a Debt MUST serialize on the parent Debt row per §2.1

## 3.6 Idempotency Fingerprints

Debt uses the request idempotency table from [[0042]]. It does not define a second idempotency mechanism.

Each idempotency fingerprint is a hash of canonical JSON. Field order is stable, timestamps are normalized to UTC ISO 8601, amounts are integer minor units, and insignificant display-only whitespace is normalized before hashing.

Fingerprints MUST include:

- `operation`
- `ledger_id`
- `debt_id` or the narrower target id (`proposal_id`, `repayment_id`) when applicable
- `actor_account_id`
- `expected_debt_row_version` for fold-changing writes that use parent CAS
- the business payload fields that affect the committed fact or workflow transition

Idempotency retry rule:

- A client MUST reuse the same `expected_debt_row_version` with the same `Idempotency-Key`; a normal retry must not recompute that field.
- Recomputing `expected_debt_row_version` after seeing newer Debt state is a new user intent and MUST use a new `Idempotency-Key`.

Operation-specific payload fields:

- repayment commit: amount or original payment input, `paid_at`, optional `proposal_id`
- repayment proposal create: proposed amount or original payment input, `paid_at`, debtor, creditor, explicit expiry when supplied, superseded proposal public id when replacing a pending proposal
- proposal resolve: `proposal_id`, resolution operation, optional `confirmed_amount_cents`
- adjustment: signed amount, reason
- repayment void: `repayment_id`, reason
- Debt void: `debt_id`, reason

Fingerprints MUST NOT include:

- server-generated ids for newly created facts
- `created_at` / `updated_at`
- post-mutation `row_version`
- presentation-only copy or labels that do not affect the business fact

Same key + same fingerprint returns the canonical committed result. Same key + different fingerprint returns `idempotency_key_reused`.

Fact tables may store the request `idempotency_key` for audit/provenance, but MUST NOT enforce it as a global unique key. Uniqueness belongs to [[0042]]'s tenant-scoped `(tenant_id, idempotency_key)` claim table so two ledgers can legitimately use the same client-generated key.

## 3.7 DebtForgiveness (landed — slice 8e-3)

Creditor waiver ("算了，不用还了") is the Communal escape valve (see §7.0): the
creditor relinquishes their own remaining claim so the debtor no longer owes it.

Fold semantics (binding):

- `DebtForgiveness` is an append-only fact (`debt_forgivenesses`: `id` / `public_id` /
  `debt_id` FK / `amount_cents` / `actor_account_id` / `idempotency_key` / `created_at`;
  `CHECK amount_cents > 0`; no global `UNIQUE(idempotency_key)` — uniqueness is
  tenant-scoped in `api_idempotency_keys`, §3.6). Its amount is the `remaining_before`
  snapshotted while serialized on the parent Debt row per §2.1 (a concurrent repayment
  and forgiveness must not both read the same pre-state and drive `remaining < 0`).
- `compute_remaining` subtracts forgiveness, so a forgiven Debt folds to `cleared`,
  NOT `voided` (`derive_status` only returns `voided` for an explicit DebtVoid). The
  read response carries `is_forgiven` (= `status == cleared` AND a forgiveness fact
  exists) so the client can tell a gift apart from a settle.
- Forgiveness is NOT a repayment: it does not contribute to `paid` (no money changed
  hands), only to the `remaining` reduction.
- A forgiven Debt is a completion: it counts toward "two-clear" in `debt_repayment`
  goals (§6). It is a one-sided creditor op (benefits the debtor only, no adverse
  interest) and so does NOT require debtor confirmation — distinct from member Debt
  void / principal-increasing adjustment (§3.3, §3.5), which keep adverse-interest
  confirmation.
- Authorization: member Debt only, creditor only. It supersedes any pending
  `MemberRepaymentProposal` in the same transaction (an unconditional guarded flip to
  `superseded` — the debtor's "I paid" intent is moot once forgiven) and surfaces that
  to the debtor via the forgiven headline. A Debt that already folds to 0 (settled or
  already forgiven) is rejected `state_conflict` (409) rather than recording a
  zero-amount fact.
- Idempotency: uses §3.6's fingerprint (`operation=forgive`, `debt_id`,
  `actor_account_id`, `expected_debt_row_version`); no second mechanism.

Open items resolved in slice 8e-3:

- **Reversal**: a committed forgiveness is FINAL in 8e-3. A mistaken forgiveness is
  corrected by re-creating the obligation (a new Debt), not by an inverse append-only
  fact — keeping forgiveness a deliberate, relationship-level gift rather than a
  reversible ledger entry. (A future inverse fact may be added if a real need arises.)
- **Goal integrity**: forgiving a Debt does NOT trigger the §6 / F13 integrity-review.
  A forgiveness folds to `cleared` (a genuine completion), which the `debt_repayment`
  evaluator already counts toward achievement — unlike a `DebtVoid` (→ `voided`), which
  is the only state that raises `needs_review`. So forgiving a goal-linked Debt advances
  the goal exactly like a repayment would; no review is forced.

---

# 4. Bill Split Linkage

Bill split acceptance is the default source for member Debt.

When Debt rollout is enabled, accepting a `BillSplitInvitation` MUST also insert one `Debt` in the existing accept transaction:

- `source_type = bill_split`
- `source_id = invitation.public_id`
- `direction = i_owe` from the receiver's perspective
- `counterparty_type = member`
- `counterparty_account_id = invitation.sender_account_id`
- `principal_amount_cents = invitation.amount_cents` (the agreed HOME-currency share)
- `home_currency_code = invitation.home_currency_code` (frozen from the snapshot, not the live setting)
- the Debt is strict home-shape: original-currency provenance fields (`original_currency_code` / `original_amount_minor` / `exchange_rate_*`) are NULL. The receiver owes a home-currency share, not a foreign principal. The invitation's frozen original-currency snapshot is the PARENT expense's full original amount, not this share, so copying it onto a share-sized principal would misstate the obligation as the full foreign amount and break the `principal ≈ original × rate` relationship. The foreign origin stays auditable via `source_type` / `source_id` → the invitation, which retains the full snapshot.
- `ledger_id = target_ledger_id`
- `owner_account_id = receiver_account_id`

This insertion MUST be in the same transaction as:

- receiver-side expense creation
- invitation `invited -> accepted` claim
- invitation accepted-state binding

All three outcomes commit together or none commit.

Uniqueness:

- one accepted invitation creates at most one receiver expense
- one accepted invitation creates at most one `Debt(source_type=bill_split, source_id=invitation.public_id)`
- re-accept returns the existing accepted result and MUST NOT create another Debt

Rejected, cancelled, or expired invitations create no Debt.

Existing accepted invitations from before Debt rollout ARE backfilled (P3b): `bill_split_service.backfill_bill_split_debts` creates the missing member Debt — byte-identical to the inline accept linkage — for every accepted split with no `bill_split` Debt, driven at startup by `reconcile_bill_split_debts_if_enabled` ONLY when the rollout is ON. While the rollout is OFF an accepted split legitimately has no Debt, so the reconcile is a no-op then (it must not fabricate obligations for the closed period); it is idempotent and `uq_debts_source` backstops a double-insert.

Bill-split linkage is default-on for accepted invitations after rollout. Opt-out requires a future product decision and ADR update.

---

# 5. Authorization

Debt uses existing ledger roles:

- `viewer`: read only
- `member` / `owner`: may write within the owning ledger subject to the rules below

## 5.1 External Debt

External debt has no in-app adverse counterparty.

- A writer on the owning ledger may create external Debt.
- A writer on the owning ledger may record repayment or adjustment.
- External labels are user-entered provenance, not account identity.

## 5.2 Member Debt

Member debt has adverse interests.

Creation rules:

- bill-split-sourced member Debt is valid only because the debtor accepted the split invitation
- a creditor cannot unilaterally create member Debt against another account
- manual member Debt that increases another party's burden requires that affected party's confirmation before becoming committed

Repayment rules:

- debtor saying "I paid" creates a pending repayment proposal
- creditor confirmation commits that repayment
- creditor partial confirmation commits only the confirmed amount and closes the proposal
- debtor withdrawal or proposal expiry commits no repayment
- creditor may directly record "I received payment" because it reduces the creditor's own receivable
- pending repayment proposals do not reduce `remaining`

Adjustment rules:

- an adjustment that increases a member's burden requires that member's confirmation
- an adjustment that reduces a creditor's receivable requires creditor confirmation
- beneficiary-only adjustment remains pending and non-authoritative

Participant confirmation must not expose private ledger internals across accounts. It may expose only the Debt shell facts required to confirm or dispute the obligation.

---

# 6. Goals

The goal system may support multiple goal types:

- `spending_limit`
- `savings_target`
- `debt_repayment`

This ADR defines only the Debt-backed `debt_repayment` semantics.

`debt_repayment` goal configuration:

- links to explicit Debt ids
- freezes the linked Debt set per goal version
- stores target period/scope as goal configuration

Achievement:

```text
achieved when every linked Debt has status=cleared
```

Rules:

- adding or removing linked Debt creates a new goal version
- unlinking an open Debt MUST NOT retroactively achieve an older version
- achievement is latched per goal version
- achievement is sticky once latched: a version with `achieved_version == goal_version` stays `achieved` and is NEVER reverted to `in_progress` / `not_evaluable`. A correction to an already-cleared linked Debt does not retroactively un-achieve a completed version. Two correction events are distinguished (ratified 2026-06-15, refining the initial resolution):
  - **reopen** (a linked Debt's repayment is voided, or a positive adjustment pushes `remaining > 0`, so its fold status returns to `open`): the achieved version stays `achieved` with NO review prompt — a routine balance change on an already-completed goal is informational only.
  - **debt-void** (a linked Debt is itself voided via `DebtVoid`, fold status `voided` — "this obligation never validly existed"): the achieved version stays `achieved` (the latch is not reverted) BUT the API/UI MUST raise a one-time **integrity review** (`needs_review = true`) forcing the user to acknowledge. This is the heavier "the basis of this achievement was ruled invalid" event and gets its own channel rather than passing silently.
- a voided linked Debt makes a NOT-yet-achieved version `not_evaluable` + `needs_review` (F13); the default policy is `not_evaluable` until the user reviews links. (An already-achieved version is the integrity-review case above — `achieved` + `needs_review`, not `not_evaluable`.)
- the integrity review (achieved + debt-void) has exactly two exits, both via existing version machinery — it never silently clears: (a) **remove the voided Debt** by replacing the link set → a new goal version that re-evaluates clean; or (b) **keep it for audit** via an explicit acknowledge action that records the acknowledgement against the current goal version, clearing `needs_review` for that version. The acknowledgement is goal-version-scoped: a later link change creates a new version whose integrity (if it still carries a voided Debt) must be re-acknowledged.
- `not_evaluable` MUST NOT be silent: the UI/API must surface that a linked Debt was voided and offer a review action such as "remove this Debt from the goal" or "keep it for audit"
- if every non-voided linked Debt is cleared and the only blocker is a voided linked Debt, the user review action creates a new goal version; the old version remains historically not evaluable unless explicitly resolved by that version policy

Implementation note:

- the current DB/API check that only permits `spending_limit` must be widened before exposing this feature
- evaluator and tests must land in the same implementation slice

---

# 7. Mascot Events

## 7.0 Member Debt Is Communal, Not Market

Member debt and external debt are the same domain (§0) but they are NOT the same
relationship. They must be framed differently in the product surface.

- External debt (`counterparty_type=external`: credit card, landlord, loan) is a
  Market Pricing relationship. The accounting frame is correct there: principal,
  remaining, paid, adjust, void, "you owe ¥X". Keep it businesslike.
- Member debt (`counterparty_type=member`: family) is a Communal Sharing
  relationship. A businesslike, settle-to-zero frame actively harms the bond.

Why this is a contract concern and not just copy: in relational-models terms
(Fiske; Clark & Mills), relationship type and the medium of exchange are tightly
linked — answering a family member's welfare gesture with a precisely priced,
settle-to-zero ledger tends to be read as re-framing a Communal bond as a Market
exchange. A child who "settles up" a parent's gift briskly and exactly can signal
"I'd rather owe you nothing", i.e. declining the bond. The offense is not the
repayment; it is rendering the relationship in Market medium (running balance,
scorecard, efficient settlement). The same literature grounds §7's existing
de-moralization rule: guilt (about a behavior) tends to drive repair, while shame
(about the self) tends to drive withdrawal — so a shame or manipulative-guilt
frame is the less effective way to resolve a family debt, not the tougher one.
Manipulative guilt ("you should have paid sooner", "you could clear this faster")
is banned on member surfaces for the same reason. These are design-orientation
grounds, not precise effect-size claims; the rules below do not depend on the
magnitude of any single effect.

The cure for "too businesslike" is NOT opacity. Hidden or silently-tallied
imbalance breeds its own resentment, so "明算账护关系" and "不 businesslike" are
not in tension. State stays fully legible; the frame is what changes.

Member-debt product rules (these constrain UI and copy, mascot included):

- Amounts and state remain fully visible and accurate; numbers do not disappear.
- Numbers MUST NOT be the hero. The hero frame is the shared thing and each
  party's fair share (Equality-Matching), not "A owes B ¥X". Precise amounts live
  one tap away (an expandable detail), never in the headline.
- No persistent running total, debtor/creditor standing balance, lifetime
  ledger, ranking, or success-vs-failure highlight is shown for member debt.
  Resolved items recede into neutral history (settle-and-forget); they do not
  accumulate into a scorecard, and no resolved row is visually singled out as a
  "successful collection".
- No shame and no manipulative guilt: no overdue/red/"催"/"欠你" framing, and no
  "you should have paid sooner" / "clear it faster" pressure, on any member-debt
  surface.
- Creditor acknowledgment is a warm person-to-person thank-you, never a
  verification/receipt. Rejection opens a conversation ("金额对不上？"), it is
  not an accusation. After a rejection the debtor gets a neutral re-propose path,
  not a dead grey badge.
- Member debt MUST NOT be packaged into a debt-payoff dashboard. A pay-down view
  containing member debt shows count-based progress and one line of relational
  copy; it does NOT add a payoff-ordering optimizer (snowball/avalanche/custom),
  a projected payoff date, or percentage milestone nudges. Those belong only to
  pure-external-debt plans (a genuine Market relationship).

Creditor waiver ("算了，不用还了") is the canonical Communal escape valve —
Communal Sharing explicitly permits giving without return. A creditor
relinquishing their own claim benefits the debtor only and carries no adverse
interest, so it is a single-sided creditor op. It is therefore distinct from
member Debt void / principal-increasing adjustment (§3.3, §3.5), which CAN harm
the counterparty and MUST keep adverse-interest confirmation. Waiver is a
first-class member-debt action; void/adjust consent rules are unchanged.

Waiver is a fold-algebra change, not a pure UI op — its binding fact spec, fold
semantics, and open invariants (reversal, goal-integrity, §2.1 serialization) are
defined in §3.7 (landed in slice 8e-3). What §7 cares about: a forgiven Debt folds
to `cleared` and is a completion that counts toward "two-clear" in plans, but it
is celebrated differently from a mutual settlement — the debtor was given
something, not made square — so it does NOT fire the settle celebration (see §4.1
of the mascot brief).

Debt events may feed the mascot, but mascot state is presentation-only.

Allowed debt-derived events:

- `DebtCreated` -> concerned / attentive
- `DebtCleared` -> celebrating
- `AllDebtsCleared` -> larger celebration

Rules:

- bill-split-sourced day-to-day Debt creation is silent by default
- Debt-created reactions must be de-moralized; no shame/punishment/dejected semantics
- clear celebrations trigger only on committed transition from open to cleared
- `AllDebtsCleared` is scoped to one `(ledger_id, owner_account_id, direction)` tuple and fires only when that tuple has no remaining non-voided open Debt after an `open -> cleared` transition
- `AllDebtsCleared` MUST NOT mix `i_owe` with `owed_to_me`, aggregate all family members, or cross ledgers
- a separate goal-scoped celebration may fire when one `debt_repayment` goal version's linked set is achieved; it is not the global `AllDebtsCleared` event
- transition dedupe marker is required before replay/sync/rebuild can feed mascot events
- dedupe marker is presentation metadata, not financial truth

---

# 8. Non-Goals

This ADR does not implement:

- Splitwise-style pair netting or settlement graph
- a separate Liability domain
- live revolving credit-card balances
- interest accrual
- credit-balance / asset semantics
- external bank/card integrations
- realized-income ledger
- cross-ledger shared expense visibility

External Debt v1 is fixed-principal / installment / IOU only.

---

# 9. Failure Model

## F1: Sender edits original expense after bill split accept

-> no effect on bill-split-sourced Debt

## F2: Receiver edits received expense

-> no effect on Debt principal

## F3: Duplicate accept

-> returns existing accepted result; creates no duplicate receiver expense and no duplicate Debt

## F4: Creditor tries to create manual member Debt unilaterally

-> remains pending or rejected; no committed Debt

## F5: Debtor records "I paid" for member Debt

-> pending repayment proposal; `remaining` unchanged until creditor confirms; expiry/withdrawal/rejection commits no repayment

## F6: Creditor records "I received"

-> committed repayment; `remaining` decreases once

## F7: Duplicate repayment submit

-> idempotency returns canonical result; balance changes once

## F8: Repayment exceeds remaining

-> rejected inside the parent Debt serialized section; no silent clamp, no direction flip

Concurrent case: if two distinct repayment intents each read `remaining=100` and each tries to commit `60`, only the first serialized writer can commit. The second must recheck current facts, see `remaining=40`, and reject or require a new user intent.

## F9: Wrong principal

-> append `DebtAdjustment`; do not mutate principal

## F10: Wrong repayment

-> append `RepaymentVoid`; do not delete repayment

## F11: Projection loss

-> recompute Debt views from Debt + DebtAdjustment + Repayment + RepaymentVoid + DebtVoid facts

## F12: Foreign-currency close-out drift

-> Debt arithmetic remains home-currency authoritative; use explicit `DebtAdjustment(reason=fx_closeout)` rather than auto-revaluing or silently clamping

## F13: Linked Debt is voided while attached to a repayment goal

-> if the goal version has NOT yet latched achievement, it becomes `not_evaluable` with a required user review prompt; it must not silently freeze forever. An already-achieved (latched) version stays `achieved` (sticky, §6) but raises a one-time integrity review (`needs_review`) — the achievement is not reverted, yet the user is forced to acknowledge (keep-for-audit) or remove the voided Debt (→ new version). A mere reopen (repayment void / positive adjustment, fold status back to `open`) on an achieved version raises NO review — only `DebtVoid` does.

---

# 10. Implementation Constraints

Minimum new structures:

- `debts`
- `repayments`
- `debt_adjustments`
- `repayment_voids`
- `debt_voids`
- `member_repayment_proposals`
- member adjustment proposal workflow records if member Debt adjustment flows are exposed; they must mirror §3.2's explicit fields, terminal lifecycle, and one-pending-per-Debt invariant
- `debt_goal_links` or equivalent versioned goal-link table
- debt mascot transition dedupe markers if mascot integration is exposed

Hard constraints:

- `remaining` is derived
- `paid` is derived
- `principal_amount_cents` is immutable after creation
- bill-split Debt source has a unique `(source_type, source_id)`
- repayments, adjustments, and voids are append-only
- all money-changing writes are tenant/account scoped from `AuthContext`
- all outbox-routed writes carry `Idempotency-Key`
- all mutable config/state rows use `row_version`
- every fold-changing child fact commit serializes on and bumps/locks the parent `Debt` row
- `member_repayment_proposals` has a partial unique index enforcing at most one pending repayment proposal per Debt
- member adverse-interest writes require affected-party confirmation before becoming committed
- all Debt fold math uses home-currency minor units; original-currency fields are provenance only

---

# 11. Confirmation

Required checks before exposing Debt features:

- bill split accept creates receiver expense and bill-split Debt in one transaction
- duplicate accept creates no duplicate Debt
- bill-split Debt freezes the invitation's home-currency share + home currency; original-currency provenance is NOT copied onto the Debt (it stays auditable via source_id → the invitation)
- sender editing original expense does not change Debt
- receiver editing received expense does not change Debt
- external Debt can be repaid/adjusted by authorized writer only
- viewer cannot create, repay, adjust, void, or link Debt
- creditor cannot unilaterally create committed member Debt
- debtor repayment proposal has explicit fields, expiry, and terminal lifecycle states
- database partial unique index prevents more than one pending repayment proposal for the same Debt
- creating a replacement proposal supersedes the explicitly named current pending proposal instead of leaving both confirmable
- stale replacement creates cannot supersede a newer pending proposal the client has not seen
- two concurrent proposal creates for the same Debt cannot leave two pending proposals
- debtor can withdraw a pending proposal without changing remaining
- changing a pending proposal amount creates a superseding proposal rather than editing in place
- superseded proposals cannot be confirmed
- creditor partial confirmation commits only the confirmed amount and closes the proposal
- expired/rejected/withdrawn/superseded proposals do not reduce remaining
- debtor-only repayment proposal does not reduce remaining
- creditor confirmation commits a debtor repayment proposal exactly once
- a member Debt's creditor who is NOT a member of the debtor's ledger can confirm/reject/clear it (account-scoped participant resolution, §5.2 / §0.1)
- a participant who is not a member of the Debt's ledger sees only the Debt shell, with the counterparty's ledger id redacted (§5.2)
- a non-participant gets `debt_not_found` for cross-ledger read/list/confirm (existence hiding, no enumeration leak)
- creditor-recorded receipt commits repayment exactly once
- adjustment increasing a member's burden requires that member's confirmation
- adjustment reducing a creditor's receivable requires creditor confirmation
- repayment replay with same idempotency key/fingerprint changes remaining once
- idempotency key reused with different fingerprint is rejected
- idempotency fingerprint fields are canonicalized and stable for repayment, adjustment, void, and proposal flows
- retries with the same idempotency key reuse the same `expected_debt_row_version`; refreshing the expected version requires a new key
- repayment exceeding remaining is rejected
- two concurrent distinct repayments against the same Debt cannot both pass an over-remaining fold check
- repayment, adjustment, repayment void, and Debt void commits bump or lock the parent Debt row in the same transaction
- foreign-currency Debt principal is frozen as home-currency authoritative amount using [[0027]]
- foreign-currency repayment uses the `paid_at` FX snapshot and freezes home-currency amount
- FX close-out drift is resolved only by explicit adjustment, not silent clamp or automatic principal revaluation
- `remaining` recomputes from append-only facts
- Debt clears only on open -> cleared transition
- wrong repayment is corrected by `RepaymentVoid`, not deletion
- wrong principal is corrected by `DebtAdjustment`, not mutation
- `debt_repayment` goal achievement requires all linked debts cleared
- `debt_repayment` linked Debt set is frozen per goal version
- voided linked Debt makes a goal version not evaluable with a visible review action
- bill-split-sourced DebtCreated is silent by default for mascot
- DebtCleared and AllDebtsCleared mascot events are transition-deduped
- AllDebtsCleared is scoped by ledger, owner account, and direction
- Debt-created mascot reaction is concerned/attentive, never shame/punishment/dejected

---

# End of Contract
