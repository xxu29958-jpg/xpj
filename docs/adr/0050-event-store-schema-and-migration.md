# ADR 0050: Event Store Schema & Migration Plan

Status: Proposed
Date: 2026-06-14
Supersedes: ADR-0049 v2 (domain design)
Type: Execution / Data Layer / Migration

---

# 1. Context

ADR-0049 defines a hybrid financial model:

- A: Splitwise-style derived member debt
- B: Monarch-style liability accounts
- C: derived savings KPI layer

However, ADR-0049 is intentionally abstract:

> It defines semantics but NOT persistence strategy

This ADR defines:

- event storage model
- schema design
- migration strategy
- reconstruction rules

---

# 2. Core Problem

We must guarantee:

- full reconstructability of financial state
- idempotent mutation handling
- no dual source of truth
- safe evolution from existing expense ledger

Key risk:

> introducing debt/liability without breaking existing expense system

---

# 3. Design Principle

## Single Truth Rule

All financial state MUST derive from append-only events.

No table is allowed to store:

- balances
- net debt
- savings

except liability_account (stateful exception, explicitly allowed in ADR-0049)

---

# 4. Event Model

## 4.1 Base Event Table

```sql
financial_events (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  type TEXT NOT NULL,
  created_at TIMESTAMP NOT NULL,

  -- identity / idempotency
  idempotency_key TEXT UNIQUE,

  -- payload
  payload JSON NOT NULL
)
```

---

## 4.2 Event Types

### A: Split System

- SplitAcceptedEvent
- MemberSettlementEvent

### B: Liability System

- LiabilityCreatedEvent
- LiabilityPaymentEvent

### C: Goal System

- GoalCreatedEvent
- GoalProgressEvent
- GoalAchievedEvent

### D: Mascot

- DebtIncreasedEvent
- DebtClearedEvent
- GoalAchievedEvent

---

# 5. Derived State Rules

## 5.1 Member Net Debt

Computed from:

- SplitAcceptedEvent
- MemberSettlementEvent

Rule: pure reducer (no storage)

---

## 5.2 Liability State

Stateful table allowed:

```text
liability_account
```

BUT mutation MUST be driven by:

- LiabilityCreatedEvent
- LiabilityPaymentEvent

---

## 5.3 Savings

Derived from:

- all inflow/outflow events
- liability adjustments excluded from asset side

NO storage allowed

---

# 6. Schema Additions

## 6.1 Liability Table

```sql
liability_account (
  id TEXT PRIMARY KEY,
  tenant_id TEXT NOT NULL,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  original_amount_cents INTEGER NOT NULL,
  current_balance_cents INTEGER NOT NULL,
  status TEXT NOT NULL
)
```

---

## 6.2 No Debt Table (Explicit)

> IMPORTANT: DO NOT CREATE

- debt table
- balance table
- net_position table

These are strictly forbidden

---

# 7. Reconstruction Engine

System MUST support:

```text
rebuild_state(events) -> full system state
```

Rules:

- events are immutable
- ordering by created_at + id
- idempotency_key prevents duplicates

---

# 8. Migration Strategy

## Phase 1: Add event table

- zero impact on existing expense ledger
- write-only parallel stream

---

## Phase 2: Dual-write bridge

- existing expense writes emit financial_events
- no read dependency yet

---

## Phase 3: Derived A layer

- enable net debt computation
- read-only integration

---

## Phase 4: Enable liability system

- new events drive account updates

---

## Phase 5: Goal + Mascot integration

- event consumers attached

---

# 9. Failure Modes & Protection

## F1: Duplicate writes

Mitigation:

- idempotency_key UNIQUE constraint

---

## F2: Out-of-order events

Mitigation:

- deterministic sort: (created_at, id)

---

## F3: Partial migration state

Mitigation:

- dual-write + shadow read mode

---

## F4: inconsistent derived balance

Mitigation:

- full rebuild validation job

---

# 10. System Invariants

I1: No balance persistence outside liability_account

I2: All debt is derived

I3: All savings is derived

I4: Events are immutable

I5: Tenant isolation enforced at event layer

---

# 11. API Impact

No direct API exposes event store.

All APIs must go through:

- reducers
- domain services

---

# 12. Consequences

## Positive

- full auditability
- deterministic financial reconstruction
- safe evolution from current system

## Negative

- increased system complexity
- requires strict discipline on event creation
- migration requires careful dual-write period

---

# 13. Final Statement

This ADR turns the system from:

> CRUD ledger

into:

> event-sourced financial system with hybrid stateful exception layer

---

# Index

ADR-0050 supersedes ADR-0049 v2
Next: ADR-0051 (query layer + optimization cache strategy)
