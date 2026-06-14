# ADR 0049: Debt Domain Contract

Status: Accepted (Target Contract; Runtime Subset)
Date: 2026-06-14
Type: Domain Contract
Lineage: replaces the earlier `financial-domain-contract` wording and consolidates the retired early drafts `0049-debt-and-liability-tracking` and `0050-event-store-schema-and-migration`.

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

---

# 3. Repayment and Correction Facts

## 3.1 Repayment

`Repayment` is append-only.

`Repayment` means a committed repayment fact. A pending "I paid" proposal for member Debt is workflow state and MUST NOT enter the repayment fold until confirmed.

Required fields:

- `repayment_id` / `public_id`
- `debt_id`
- `amount_cents`
- `paid_at`
- `actor_account_id`
- `idempotency_key`
- `created_at`

Rules:

- `amount_cents > 0`
- replays with the same idempotency key and fingerprint return the same committed repayment
- replays with mismatched fingerprint return `idempotency_key_reused`
- a repayment that would make `remaining < 0` is rejected
- repayment never mutates the Debt principal

## 3.2 DebtAdjustment

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

## 3.3 RepaymentVoid

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

## 3.4 Debt Void

Voiding an entire Debt is allowed only through an append-only correction fact.

Rules:

- bill-split-sourced Debt voiding requires the same adverse-interest confirmation rules as member Debt adjustment
- voided Debt no longer contributes to open debt totals or goals
- voided Debt remains visible in audit/history

---

# 4. Bill Split Linkage

Bill split acceptance is the default source for member Debt.

When Debt rollout is enabled, accepting a `BillSplitInvitation` MUST also insert one `Debt` in the existing accept transaction:

- `source_type = bill_split`
- `source_id = invitation.public_id`
- `direction = i_owe` from the receiver's perspective
- `counterparty_type = member`
- `counterparty_account_id = invitation.sender_account_id`
- `principal_amount_cents = invitation.amount_cents`
- currency/provenance copied from the frozen invitation snapshot
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

Existing accepted invitations from before Debt rollout are not automatically backfilled by this ADR. Backfill, if needed, requires an explicit migration plan and reconciliation check.

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
- voided linked Debt requires explicit goal-version policy before exposure; default is to make the current version `not_evaluable` until user reviews links

Implementation note:

- the current DB/API check that only permits `spending_limit` must be widened before exposing this feature
- evaluator and tests must land in the same implementation slice

---

# 7. Mascot Events

Debt events may feed the mascot, but mascot state is presentation-only.

Allowed debt-derived events:

- `DebtCreated` -> concerned / attentive
- `DebtCleared` -> celebrating
- `AllDebtsCleared` -> larger celebration

Rules:

- bill-split-sourced day-to-day Debt creation is silent by default
- Debt-created reactions must be de-moralized; no shame/punishment/dejected semantics
- clear celebrations trigger only on committed transition from open to cleared
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
- automatic backfill of old accepted bill splits

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

-> pending repayment proposal; `remaining` unchanged until creditor confirms

## F6: Creditor records "I received"

-> committed repayment; `remaining` decreases once

## F7: Duplicate repayment submit

-> idempotency returns canonical result; balance changes once

## F8: Repayment exceeds remaining

-> rejected; no silent clamp, no direction flip

## F9: Wrong principal

-> append `DebtAdjustment`; do not mutate principal

## F10: Wrong repayment

-> append `RepaymentVoid`; do not delete repayment

## F11: Projection loss

-> recompute Debt views from Debt + DebtAdjustment + Repayment + RepaymentVoid + DebtVoid facts

---

# 10. Implementation Constraints

Minimum new structures:

- `debts`
- `repayments`
- `debt_adjustments`
- `repayment_voids`
- member repayment/adjustment proposal workflow records if member Debt write flows are exposed
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
- member adverse-interest writes require affected-party confirmation before becoming committed

---

# 11. Confirmation

Required checks before exposing Debt features:

- bill split accept creates receiver expense and bill-split Debt in one transaction
- duplicate accept creates no duplicate Debt
- bill-split Debt uses frozen invitation amount/currency/provenance
- sender editing original expense does not change Debt
- receiver editing received expense does not change Debt
- external Debt can be repaid/adjusted by authorized writer only
- viewer cannot create, repay, adjust, void, or link Debt
- creditor cannot unilaterally create committed member Debt
- debtor-only repayment proposal does not reduce remaining
- creditor confirmation commits a debtor repayment proposal exactly once
- creditor-recorded receipt commits repayment exactly once
- adjustment increasing a member's burden requires that member's confirmation
- adjustment reducing a creditor's receivable requires creditor confirmation
- repayment replay with same idempotency key/fingerprint changes remaining once
- idempotency key reused with different fingerprint is rejected
- repayment exceeding remaining is rejected
- `remaining` recomputes from append-only facts
- Debt clears only on open -> cleared transition
- wrong repayment is corrected by `RepaymentVoid`, not deletion
- wrong principal is corrected by `DebtAdjustment`, not mutation
- `debt_repayment` goal achievement requires all linked debts cleared
- `debt_repayment` linked Debt set is frozen per goal version
- bill-split-sourced DebtCreated is silent by default for mascot
- DebtCleared and AllDebtsCleared mascot events are transition-deduped
- Debt-created mascot reaction is concerned/attentive, never shame/punishment/dejected

---

# End of Contract
