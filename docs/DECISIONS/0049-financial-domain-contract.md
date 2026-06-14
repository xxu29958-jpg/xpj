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

# 2. Security and Authorization Contract

Money-changing operations MUST derive actor identity and tenant scope from the authenticated server-side `AuthContext`. They MUST NOT trust caller-supplied account, ledger, or tenant ids as authority.

## 2.1 Tenant Isolation

- No member-debt, liability, goal, or mascot derivation may cross tenant/account scope unless an explicit product configuration authorizes that scope.
- All financial writes MUST be scoped by tenant/account on the server side.
- Cross-tenant derivation is forbidden.

## 2.2 Participant Authorization

- Split invitation accept: only `receiver_account_id` may accept, and the receiver must choose a target ledger where they have write role.
- Split invitation reject: only `receiver_account_id` may reject.
- Split invitation cancel: only `sender_account_id` may cancel before acceptance.
- Member settlement create/reverse/void: only a participant in that account pair may perform the operation.
- Liability create/update/payment/adjustment: only an actor with write permission on the liability's owning scope may perform the operation.
- Goal create/update/archive: only an actor with write permission on the goal's owning scope may perform the operation.

Third-party account C MUST NOT be able to create, reverse, void, or otherwise affect financial facts between accounts A and B.

APIs SHOULD avoid confirming whether a nonparticipant-guessed financial id exists. Prefer `not_found` or an equivalent non-enumerating error shape for unauthorized nonparticipants.

## 2.3 Idempotency Baseline

All money-changing operations MUST have an explicit idempotency contract.

- Operations with a natural domain key may use domain uniqueness as the primary guard. Example: one invitation may create at most one accepted split snapshot.
- Append/state mutations without a natural single-result key MUST use a request idempotency key. This includes settlements, settlement reversals, snapshot voids, liability mutations, and goal writes.
- The request idempotency key is generated at user-intent time.
- The server persists a fingerprint under `(tenant_id, actor_account_id, operation, target_type, idempotency_key)`.
- A replay with the same key and same fingerprint returns the canonical success result.
- A replay with the same key and different fingerprint returns `idempotency_key_reused`.
- Resource ids such as `settlement_id` or `liability_mutation_id` MUST NOT be the only idempotency guard.

Domain uniqueness still applies in addition to request idempotency where relevant. For example, one invitation may create at most one accepted split snapshot, and one settlement may be reversed at most once.

---

# 3. A - Member Debt Contract

## 3.1 Source of Truth

Member debt is derived ONLY from:

- `AcceptedSplitSnapshot`
- `AcceptedSplitVoid`
- `MemberSettlement`
- `MemberSettlementReversal`

No other source is valid.

---

## 3.2 Accepted Split Rule (Critical)

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

## 3.3 Accept Atomicity

Accepting a split invitation MUST be atomic:

- create the receiver-side expense snapshot if the product flow requires one
- create the accepted split snapshot
- mark the invitation as accepted

These changes MUST commit together or not commit at all.

Accept is idempotent. Replaying the same accept intent MUST return the existing accepted result and MUST NOT create another debt snapshot.

Domain uniqueness:

- `invitation_id` MUST be unique among accepted split snapshots.
- A second accept attempt for the same invitation MUST return the existing accepted result or a state conflict, never another snapshot.

---

## 3.4 Snapshot Void Contract

If an accepted split is wrong, the correction path is an append-only void/dispute event, not fake settlement.

`AcceptedSplitVoid` MUST:

- reference exactly one accepted split snapshot
- be idempotent via its request idempotency key and `void_id`
- include actor, reason, and timestamp
- be authorized to a participant in the accepted split
- not mutate the original snapshot
- not allow double void for the same snapshot

A voided snapshot no longer contributes to member-debt net balance, but remains visible in audit history.

---

## 3.5 Non-Rule (Explicit Decoupling)

After acceptance:

- modifying original expense MUST NOT affect debt
- modifying sender ledger MUST NOT affect debt
- receiver created expense MUST NOT affect debt
- deleting or archiving either visible ledger record MUST NOT mutate accepted debt

Debt is bound ONLY to snapshots, voids, settlements, and settlement reversals.

---

## 3.6 Net Balance Rule

For an unordered account pair `(A, B)`:

```text
net(A,B) =
  sum(non-voided snapshot A owes B)
- sum(non-voided snapshot B owes A)
- sum(settlement A pays B)
+ sum(settlement B pays A)
- sum(reversal of settlement B pays A)
+ sum(reversal of settlement A pays B)
```

Positive `net(A,B)` means A owes B.

All sums use home-currency `amount_cents` frozen at acceptance or settlement time. `currency_code` is provenance only and MUST NOT change the fold currency.

---

## 3.7 Settlement Contract

A settlement is:

- append-only financial correction between two accounts
- uniquely identified by `settlement_id`
- request-idempotent via section 2.3

### Settlement MUST:
- have `amount_cents > 0`
- use a server-scoped unique `settlement_id`
- have explicit `payer_account_id` and `payee_account_id`
- reduce the payer's existing net debt to the payee
- be admitted under a per-account-pair serialization or compare-and-append guard
- never modify past snapshots

### Settlement MUST NOT:
- create a new opposite-direction debt by overpaying
- touch liability accounts
- rewrite or delete prior settlements

### Settlement MAY:
- be reversed via explicit reversal event

Overpay prevention MUST be checked against the authoritative fold/current pair state while holding the pair admission guard. Rebuildable projections or caches MUST NOT be used for admission. If pair-level admission cannot be implemented, settlement creation MUST NOT be exposed.

---

## 3.8 Account Lifecycle

Member-debt participant accounts require durable identity.

- An account with nonzero member debt MUST NOT be hard-deleted.
- Account closure requires settling or voiding all open member debt first. Write-off/forgiveness semantics require a future ADR before use.
- If product policy permits account merge, the merge MUST preserve audit identity via an append-only mapping or tombstone. Existing snapshots MUST NOT be mutated in place.
- If legal deletion is required, a non-identifying tombstone id must remain sufficient to preserve financial audit and fold correctness.

---

## 3.9 Forbidden Operations

- No authoritative debt table
- No authoritative balance table
- No mutation of snapshots

Rebuildable read projections or caches MAY exist in the future, but they are not financial truth and MUST be disposable.

---

# 4. B - Liability Contract

## 4.1 Definition

Liability is a stateful external account.

Allowed mutations:

- increase balance (debt creation)
- decrease balance (payment)
- explicit adjustment with audit reason

All liability mutations are money-changing operations and MUST follow the security and idempotency contract in section 2.

---

## 4.2 Rules

- liability is NOT part of member graph
- liability is NOT derived
- liability balance is authoritative state
- liability payment may be represented as an expense only for spending reports, not as member-debt settlement

---

## 4.3 Mutation and Audit Contract

Every liability balance mutation MUST:

- have an idempotency key and immutable `liability_mutation_id`
- append an immutable audit event in the same transaction as the state update
- include actor, mutation type, amount, reason code, timestamp, and previous/new balance
- reject replays with mismatched fingerprints
- reject mutations that would make balance negative

`explicit adjustment` is not a loophole. It MUST use a signed amount, require a non-empty reason, and remain append-only. Incorrect adjustments are corrected by another explicit adjustment, never by rewriting history.

## 4.4 Completion Rule

```text
balance == 0 -> cleared
```

`DebtCleared` is emitted only on transition from positive balance to zero. Refreshing or rereading a zero-balance liability MUST NOT emit another cleared event.

Liability overpayment is not part of this contract. A payment larger than the current balance MUST be rejected unless a future ADR introduces credit-balance or asset semantics.

---

# 5. C - Goal Contract

## 5.1 Goal Types

- `spending_limit`
- `savings_target`
- `debt_repayment`

Current runtime implementation supports only `spending_limit`. `savings_target` and `debt_repayment` are contract-level reserved goal types and MUST NOT be exposed through product/API surfaces until their storage, evaluator, authorization, and Confirmation checks are implemented.

---

## 5.2 Achievement Rules

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

The linked liability set is frozen for a goal version. Adding or removing linked liabilities creates a new goal version and MUST NOT retroactively achieve or un-achieve the previous version.

Achievement is latched per goal version. Later borrowing against a previously cleared liability may start a new repayment goal/version, but it does not rewrite the historical achievement event.

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

If no active income plan exists for the configured scope and period, `savings_target` is `not_evaluable`, not failed and not achieved.

---

# 6. Mascot Contract (Non-financial Layer)

## 6.1 Allowed Events

- `MemberDebtCleared` -> Celebrating
- `DebtCleared` -> Celebrating
- `GoalAchieved` -> Celebrating

These are presentation events derived from committed financial transitions. They are not financial state.

## 6.2 Trigger Rules

- each member-debt account pair may trigger clear celebration once per transition from nonzero net to zero net
- each liability clear transition may trigger celebration once
- each goal period achievement may trigger celebration once
- page refresh, sync replay, or projection rebuild MUST NOT retrigger celebration

Trigger-once requires a persistent dedupe marker keyed by event type, scope, and source transition. The marker is presentation metadata, not financial truth.

## 6.3 Forbidden Semantics

- No moral interpretation of debt increase
- No Dejected state tied to financial activity
- No shame, punishment, or negative character reaction for spending or borrowing

---

# 7. System Invariants

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

## I7 - Write Authorization

Every money-changing operation requires an authenticated actor with explicit participant or owner-scope write permission.

## I8 - Money Mutation Idempotency

Every money-changing operation has an explicit idempotency contract. Append/state mutations use a request idempotency key plus domain uniqueness constraints where applicable.

---

# 8. Failure Model

## F1: Sender edits original expense

-> NO EFFECT on debt

## F2: Receiver modifies local expense

-> NO EFFECT on debt

## F3: Duplicate accept

-> returns existing accepted result, creates no new snapshot

## F4: Unauthorized third party attempts member-debt write

-> rejected before any financial state changes

## F5: Duplicate settlement

-> returns the canonical settlement result via idempotency; balance changes once

## F6: Concurrent settlements for same pair

-> serialized or compare-and-append guarded so overpay cannot flip direction

## F7: Settlement reversal

-> restores previous net state through append-only reversal

## F8: Duplicate reversal

-> rejected or returned as the existing reversal result; never applied twice

## F9: Accepted snapshot is wrong

-> append `AcceptedSplitVoid`, never mutate the snapshot or fake a settlement

## F10: Duplicate liability payment

-> returns canonical success for the original mutation, balance changes once

## F11: Liability payment exceeds balance

-> rejected; no negative liability balance

## F12: Projection loss

-> recompute from snapshots, voids, settlements, reversals, liability state/audit, and scoped goal inputs

---

# 9. Non-Goals

- No event sourcing requirement
- No global financial event store
- No caching or projection design
- No full balance sheet model
- No cross-ledger shared expense visibility
- No realized-income transaction ledger

---

# 10. Contract Summary

This system guarantees:

```text
Member debt = frozen non-voided snapshots + settlements + settlement reversals
Liability = independent stateful accounts + idempotent append-only mutation audit
Goals = derived constraints over explicit scopes and goal versions
Mascot = presentation-only reaction to committed, deduped transitions
```

---

# 11. Implementation Constraints

## 11.1 Snapshot Storage Boundary

- `AcceptedSplitSnapshot` is allowed append-only storage
- It is NOT a debt table or balance table
- Forbidden:
  - mutable debt tables
  - authoritative aggregated balance tables

Only immutable financial snapshots are permitted as member-debt event sources.

---

## 11.2 Settlement & Reversal Contract

- `MemberSettlement` MUST have a unique `settlement_id` and request idempotency
- `MemberSettlementReversal` MUST:
  - reference original `settlement_id`
  - be idempotent itself
  - NOT allow double-reversal (1:1 rule)

Reversal restores previous derived net state deterministically.

If a reversal or void changes facts for a period already consumed by goals, reports, or mascot events, it creates a correction record. It MUST NOT silently rewrite previously emitted achievement or celebration events. Full restatement semantics require a future ADR.

---

## 11.3 Closed Period and Admission Contract

- Settlement admission is order-sensitive even though fold is order-independent.
- Admission MUST use pair-level serialization or an equivalent conditional compare-and-append guard.
- Admission MUST read authoritative fold/current state, not disposable cache.
- Closed-period corrections are explicit correction events, not invisible history rewrites.

---

## 11.4 Migration Constraint (Additive Only)

- All new structures are append-only additions
- Existing expense ledger MUST NOT be modified
- No backfill into legacy tables
- No dual-write rollback requirement

---

## 11.5 Derivation Correctness Contract

A-domain correctness MUST satisfy:

```text
fold(all non-voided snapshots, all settlements, all reversals) == expected net(A,B)
```

- deterministic
- order-independent except stable id tie-break
- independent of expense edits after acceptance

---

## 11.6 Read Cost Acceptance (Explicit)

- Net balance is recomputed via full fold in v1
- Complexity O(events per pair)
- Acceptable for household scale

Future optimization with a cache or projection table is explicitly deferred and NOT part of this contract. If introduced, it must remain rebuildable and non-authoritative.

---

# 12. Confirmation

Required implementation checks:

- third-party account cannot accept, settle, reverse, void, or adjust money facts for other participants
- all financial writes are tenant/account scoped from `AuthContext`
- editing sender original expense does not change member debt
- editing receiver local expense does not change member debt
- duplicate accept returns same accepted snapshot/result
- a different accept key for the same invitation cannot create a second snapshot
- accept creates receiver expense and accepted snapshot atomically
- accepted snapshot fields are immutable
- accepted snapshot void removes it from net fold without mutating it
- settlement replay with the same request idempotency key and fingerprint returns the canonical settlement result
- `settlement_id` uniqueness is a domain guard, not the only idempotency mechanism
- settlement request idempotency key cannot be reused with a different fingerprint
- settlement cannot overpay into opposite-direction debt
- concurrent settlements for the same pair cannot both pass stale net checks
- settlement reversal references original settlement and cannot be applied twice
- liability payment replay changes balance only once
- liability adjustment is append-only, reasoned, and immutable
- liability mutation cannot make balance negative
- fold order does not change final net balance
- liability balance never enters member debt graph
- debt repayment goal is achieved only when linked liabilities are all cleared
- debt repayment linked-liability changes create a new goal version
- spending limit achievement fires only after period close and only if not exceeded
- savings target progress is derived from authorized scope-bound income plans minus scoped confirmed spending
- savings target with no active income plan is not evaluable
- member-debt clear transition can produce a deduped `MemberDebtCleared` mascot event
- `DebtCleared` and `GoalAchieved` mascot events fire once per committed transition
- debt increase, spending increase, or borrowing never triggers a negative mascot state

---

# End of Contract
