# ADR 0049 (v3): Financial Domain Contract

Status: Accepted (Contract Spec)
Date: 2026-06-14
Type: Domain Contract (0042-style)

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

Peer-to-peer net balance between members.

## B. Liability (Monarch Model)

External or personal debt accounts.

## C. Goals (KPI Layer)

Non-transactional financial objectives.

---

# 2. A — Member Debt Contract

## 2.1 Source of Truth

Member debt is derived ONLY from:

- `AcceptedSplitSnapshot`
- `SettlementEvents`

No other source is valid.

---

## 2.2 Accepted Split Rule (Critical)

When a split is accepted:

> The system MUST freeze a snapshot amount at acceptance time.

### Frozen fields:
- amount_cents
- debtor_account_id
- creditor_account_id
- invitation_id

This snapshot is immutable.

---

## 2.3 Non-Rule (Explicit Decoupling)

After acceptance:

- modifying original expense MUST NOT affect debt
- modifying sender ledger MUST NOT affect debt
- receiver created expense MUST NOT affect debt

Debt is bound ONLY to snapshot.

---

## 2.4 Net Balance Rule

```
net(A,B) =
  Σ(snapshot A owes B)
- Σ(snapshot B owes A)
- Σ(settlements)
```

---

## 2.5 Settlement Contract

A settlement is:

- append-only financial correction between A and B
- idempotent via settlement_id

### Settlement MUST:
- reduce net balance
- never modify past snapshots

### Settlement MAY:
- be reversed via explicit reversal event

---

## 2.6 Forbidden Operations

- No debt table
- No balance table
- No mutation of snapshots

---

# 3. B — Liability Contract

## 3.1 Definition

Liability is a stateful external account.

Allowed mutations:

- increase balance (debt creation)
- decrease balance (payment)

---

## 3.2 Rules

- liability is NOT part of member graph
- liability is NOT derived
- liability is authoritative state

---

## 3.3 Completion Rule

```
balance == 0 → cleared
```

---

# 4. C — Goal Contract

## 4.1 Goal Types

- spending_limit
- savings_target (derived KPI only)
- debt_repayment

---

## 4.2 Achievement Rules

### debt_repayment

Achieved when:

- all linked liabilities == 0

### savings_target

Derived ONLY from system-wide net flow.

No direct storage allowed.

---

# 5. Mascot Contract (Non-financial layer)

## 5.1 Allowed Events

- DebtCleared → Celebrating
- GoalAchieved → Celebrating

## 5.2 Forbidden Semantics

- No moral interpretation of debt increase
- No Dejected state tied to financial activity

---

# 6. System Invariants

## I1 — Snapshot Immutability

Accepted splits MUST NEVER change after creation.

## I2 — Debt Isolation

Member debt MUST NOT depend on liability accounts.

## I3 — Liability Isolation

Liability MUST NOT enter member graph.

## I4 — No Dual Truth

Each financial fact has exactly one source of truth.

---

# 7. Failure Model

## F1: Sender edits original expense
→ NO EFFECT on debt

## F2: Receiver modifies local expense
→ NO EFFECT on debt

## F3: Duplicate settlement
→ ignored via idempotency

## F4: Settlement reversal
→ restores previous net state

---

# 8. Non-Goals

- No event sourcing requirement
- No global financial event store
- No caching or projection design
- No full balance sheet model

---

# 9. Contract Summary

This system guarantees:

> Member debt = frozen snapshots + settlements
> Liability = independent stateful accounts
> Goals = derived constraints only

---

# 10. Implementation Constraints

## 10.1 Snapshot Storage Boundary

- `AcceptedSplitSnapshot` is allowed append-only storage
- It is NOT a debt table or balance table
- Forbidden:
  - mutable debt tables
  - aggregated balance tables

Only immutable financial snapshots are permitted as event sources.

---

## 10.2 Settlement & Reversal Contract

- `MemberSettlement` MUST be idempotent via settlement_id
- `MemberSettlementReversal` MUST:
  - reference original settlement_id
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

fold(all snapshots, all settlements) == expected net(A,B)

- deterministic
- order-independent except settlement_id tie-break

---

## 10.5 Read Cost Acceptance (Explicit)

- Net balance is recomputed via full fold in v1
- Complexity O(events per pair)
- Acceptable for household scale

Future optimization (cache/balance table) is explicitly deferred and NOT part of contract

---

# End of Contract
