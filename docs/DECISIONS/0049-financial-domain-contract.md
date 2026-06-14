# ADR 0049: Financial Domain Contract

Status: Accepted (Contract Spec)
Date: 2026-06-14
Type: Domain Contract (0042-style)
Lineage: consolidates and replaces the retired early drafts `0049-debt-and-liability-tracking` and `0050-event-store-schema-and-migration`.

---

# 0. Scope

This ADR defines **financial truth rules only**.

It does NOT define:
- storage implementation
- event sourcing architecture
- caching strategy
- migration plan

It defines:

> what is financially true, not how it is stored

---

# 1. Core Domains

System contains three financial domains:

## A. Member Debt (Splitwise Model)

Peer-to-peer net balance between accounts.

This is account-scoped, not ledger-scoped. It preserves the privacy boundary from ADR-0029: personal ledgers remain invisible across accounts.

## B. Liability (Monarch Model)

External or personal debt accounts.

## C. Goals (KPI Layer)

Non-transactional financial objectives.

Goal configuration may be stored. Goal progress and achievement are derived from domain facts.

---

# 2. A - Member Debt Contract

## 2.1 Source of Truth

Member debt is derived ONLY from:

- `AcceptedSplitSnapshot`
- `MemberSettlement`
- `MemberSettlementReversal`

No other source is valid.

---

## 2.2 Accepted Split Rule (Critical)

When a split invitation is accepted:

> The system MUST freeze a snapshot amount at acceptance time.

### Frozen fields:
- `snapshot_id` or `public_id`
- `amount_cents`
- `currency_code`
- `debtor_account_id`
- `creditor_account_id`
- `invitation_id`
- `accepted_at`

The amount is the backend-authoritative home-currency amount at acceptance time. Later FX-rate changes MUST NOT reprice an accepted snapshot.

This snapshot is immutable.

---

## 2.3 Accept Atomicity

Accepting a split invitation MUST be atomic:

- create the receiver-side expense snapshot if the product flow requires one
- create the accepted split snapshot
- mark the invitation as accepted

These changes MUST commit together or not commit at all.

Accept is idempotent. Replaying the same accept intent MUST return the existing accepted result and MUST NOT create another debt snapshot.

---

## 2.4 Non-Rule (Explicit Decoupling)

After acceptance:

- modifying original expense MUST NOT affect debt
- modifying sender ledger MUST NOT affect debt
- receiver created expense MUST NOT affect debt
- deleting or archiving either visible ledger record MUST NOT mutate accepted debt

Debt is bound ONLY to snapshot plus settlements.

---

## 2.5 Net Balance Rule

For an unordered account pair `(A, B)`:

```text
net(A,B) =
  sum(snapshot A owes B)
- sum(snapshot B owes A)
- sum(settlement A pays B)
+ sum(settlement B pays A)
- sum(reversal of settlement B pays A)
+ sum(reversal of settlement A pays B)
```

Positive `net(A,B)` means A owes B.

All sums use home-currency `amount_cents` frozen at acceptance or settlement time. `currency_code` is provenance only and MUST NOT change the fold currency.

---

## 2.6 Settlement Contract

A settlement is:

- append-only financial correction between two accounts
- idempotent via `settlement_id`

### Settlement MUST:
- have `amount_cents > 0`
- have explicit `payer_account_id` and `payee_account_id`
- reduce the payer's existing net debt to the payee
- never modify past snapshots

### Settlement MUST NOT:
- create a new opposite-direction debt by overpaying
- touch liability accounts
- rewrite or delete prior settlements

### Settlement MAY:
- be reversed via explicit reversal event

---

## 2.7 Forbidden Operations

- No authoritative debt table
- No authoritative balance table
- No mutation of snapshots

Rebuildable read projections or caches MAY exist in the future, but they are not financial truth and MUST be disposable.

---

# 3. B - Liability Contract

## 3.1 Definition

Liability is a stateful external account.

Allowed mutations:

- increase balance (debt creation)
- decrease balance (payment)
- explicit adjustment with audit reason

---

## 3.2 Rules

- liability is NOT part of member graph
- liability is NOT derived
- liability balance is authoritative state
- liability payment may be represented as an expense only for spending reports, not as member-debt settlement

---

## 3.3 Completion Rule

```text
balance == 0 -> cleared
```

`DebtCleared` is emitted only on transition from positive balance to zero. Refreshing or rereading a zero-balance liability MUST NOT emit another cleared event.

---

# 4. C - Goal Contract

## 4.1 Goal Types

- `spending_limit`
- `savings_target`
- `debt_repayment`

---

## 4.2 Achievement Rules

### spending_limit

`spending_limit` is a guardrail, not a mid-period achievement.

Achieved only when:

- the configured period is closed
- scoped confirmed spending is below or equal to target
- the goal was active for that period

Crossing 80% or 100% during the period is warning state, not achievement.

### debt_repayment

Achieved when:

- all linked liabilities are cleared

### savings_target

Current contract: `savings_target` is a forecast-based KPI, not a realized cash ledger.

It is derived ONLY from:

```text
planned_savings = scoped income_plan amount - scoped confirmed spending
```

Forecast inflow is the sum of active `income_plan` snapshots for the same scope and period. It is not realized income.

Achievement is evaluable only when:

- the configured period is closed
- an active income plan exists for the same scope and period
- scoped confirmed spending is available for that period
- `planned_savings >= target_amount_cents`

No realized-income transaction ledger is defined by this ADR. If future product work adds actual income transactions, switching `savings_target` from forecast-based to realized-flow-based semantics requires a new ADR.

Allowed scope examples:

- current ledger
- explicit account group defined by product configuration

No cross-ledger or cross-account aggregation is allowed unless that scope is explicitly configured and authorized.

Goal target/configuration may be stored. Goal progress and achieved state MUST NOT be stored as independent truth.

---

# 5. Mascot Contract (Non-financial Layer)

## 5.1 Allowed Events

- `DebtCleared` -> Celebrating
- `GoalAchieved` -> Celebrating

These are presentation events derived from committed financial transitions. They are not financial state.

## 5.2 Trigger Rules

- each liability clear transition may trigger celebration once
- each goal period achievement may trigger celebration once
- page refresh, sync replay, or projection rebuild MUST NOT retrigger celebration

## 5.3 Forbidden Semantics

- No moral interpretation of debt increase
- No Dejected state tied to financial activity
- No shame, punishment, or negative character reaction for spending or borrowing

---

# 6. System Invariants

## I1 - Snapshot Immutability

Accepted splits MUST NEVER change after creation.

## I2 - Debt Isolation

Member debt MUST NOT depend on liability accounts.

## I3 - Liability Isolation

Liability MUST NOT enter member graph.

## I4 - No Dual Truth

Each financial fact has exactly one source of truth.

## I5 - Projection Disposability

Any cache, projection, or dashboard summary MUST be rebuildable from its source of truth and MUST NOT become a second authority.

## I6 - Ledger Privacy

Member debt may connect accounts, but it MUST NOT expose either party's private ledger internals.

---

# 7. Failure Model

## F1: Sender edits original expense

-> NO EFFECT on debt

## F2: Receiver modifies local expense

-> NO EFFECT on debt

## F3: Duplicate accept

-> returns existing accepted result, creates no new snapshot

## F4: Duplicate settlement

-> ignored via idempotency

## F5: Settlement reversal

-> restores previous net state

## F6: Duplicate reversal

-> rejected or returned as the existing reversal result; never applied twice

## F7: Projection loss

-> recompute from snapshots, settlements, liabilities, and scoped goal inputs

---

# 8. Non-Goals

- No event sourcing requirement
- No global financial event store
- No caching or projection design
- No full balance sheet model
- No cross-ledger shared expense visibility

---

# 9. Contract Summary

This system guarantees:

```text
Member debt = frozen snapshots + settlements + settlement reversals
Liability = independent stateful accounts
Goals = derived constraints over explicit scopes
Mascot = presentation-only reaction to committed transitions
```

---

# 10. Implementation Constraints

## 10.1 Snapshot Storage Boundary

- `AcceptedSplitSnapshot` is allowed append-only storage
- It is NOT a debt table or balance table
- Forbidden:
  - mutable debt tables
  - authoritative aggregated balance tables

Only immutable financial snapshots are permitted as member-debt event sources.

---

## 10.2 Settlement & Reversal Contract

- `MemberSettlement` MUST be idempotent via `settlement_id`
- `MemberSettlementReversal` MUST:
  - reference original `settlement_id`
  - be idempotent itself
  - NOT allow double-reversal (1:1 rule)

Reversal restores previous derived net state deterministically.

---

## 10.3 Migration Constraint (Additive Only)

- All new structures are append-only additions
- Existing expense ledger MUST NOT be modified
- No backfill into legacy tables
- No dual-write rollback requirement

---

## 10.4 Derivation Correctness Contract

A-domain correctness MUST satisfy:

```text
fold(all snapshots, all settlements, all reversals) == expected net(A,B)
```

- deterministic
- order-independent except stable id tie-break
- independent of expense edits after acceptance

---

## 10.5 Read Cost Acceptance (Explicit)

- Net balance is recomputed via full fold in v1
- Complexity O(events per pair)
- Acceptable for household scale

Future optimization with a cache or projection table is explicitly deferred and NOT part of this contract. If introduced, it must remain rebuildable and non-authoritative.

---

# 11. Confirmation

Required implementation checks:

- editing sender original expense does not change member debt
- editing receiver local expense does not change member debt
- duplicate accept returns same accepted snapshot/result
- accept creates receiver expense and accepted snapshot atomically
- accepted snapshot fields are immutable
- settlement replay with same `settlement_id` is idempotent
- settlement cannot overpay into opposite-direction debt
- settlement reversal references original settlement and cannot be applied twice
- fold order does not change final net balance
- liability balance never enters member debt graph
- debt repayment goal is achieved only when linked liabilities are all cleared
- spending limit achievement fires only after period close and only if not exceeded
- savings target progress is derived from authorized scope-bound income plans minus scoped confirmed spending
- `DebtCleared` and `GoalAchieved` mascot events fire once per committed transition
- debt increase, spending increase, or borrowing never triggers a negative mascot state

---

# End of Contract
