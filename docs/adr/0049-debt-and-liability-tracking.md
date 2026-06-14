# ADR 0049: 债务与负债追踪（成员净额结算 + 个人负债账户）

Status: Proposed (Accepted by maintainer 2026-06-14)
Date: 2026-06-14
Decision: A2 + B2（成员间净额 derive + 个人负债账户）

---

## Context

当前系统为纯支出账本，仅支持拆账后的独立支出记录（[[0029]]）。不存在“债务余额”概念，也没有成员间未结算状态表达。

现有目标体系仅支持 spending_limit，没有资产/负债维度，也不存在达成态语义。夹夹状态机具备庆祝态但未接入任何经济语义事件。

本次变更引入两类能力：

- A：成员间债务（Splitwise 风格净额）
- B：个人对外负债账户（Monarch / YNAB 风格）

---

## Problem Statement

需要同时支持：

1. 成员间“谁欠谁”的动态净额
2. 个人对外负债（信用卡/贷款/外部欠款）
3. 结清行为（还款/清零）
4. 负债驱动的目标与情绪反馈

核心约束：

- 不能破坏现有拆账模型
- 不能引入不一致债务行（避免双写源真相）
- 必须可验证、可派生、可恢复

---

## Decision Drivers

- 数据正确性优先（金额系统不能双真相）
- 复用拆账已有份额数据
- 业界成熟模型优先（Splitwise / Monarch / YNAB）
- tenant 隔离必须严格
- 最低冗余数据结构

---

## Considered Options

### A（成员间债务）

**A1：显式 Debt/Repayment 表（Rejected）**
- 会导致双写真相
- 债务状态漂移风险
- 结算历史复杂化

**A2：从交易 + 份额 derive net balance（Chosen）**
- Splitwise 风格
- 只存结算事件（member_settlement）
- 净额实时/批量派生

---

### B（个人负债）

**B1：复用成员模型（Rejected）**
- 外部债权方无法建模为成员

**B2：独立 liability account（Chosen）**
- Monarch/YNAB 风格
- current_balance_cents 驱动状态
- repayment 事件递减余额

---

## Decision Outcome

### A：成员间净额（Splitwise 式 derive）

#### Data Sources

- BillSplitInvitation.accepted
- member_settlement

#### Rule

net(A,B) =
Σ A 收 B 欠款
- Σ B 收 A 欠款
- Σ 双向 settlement

#### Semantics

- accept split → 隐式债务关系（不落库）
- settlement → 唯一结算写入
- 一键结清 → settlement 抵消净额

#### Properties

- 无 debt table
- 无余额冗余表（v1）
- 可完全重建

---

### B：个人负债账户

#### Entity

- liability_account
  - name
  - type: credit_card | loan | personal | other
  - original_amount_cents
  - current_balance_cents
  - status: active | cleared | archived

#### Behavior

- liability_payment → balance decrease
- balance == 0 → cleared

#### Extension

- debt_repayment goal_type

---

## Goal System

goal_type:

- spending_limit
- savings_target
- debt_repayment (new)

achieved state:

- savings_target → achieved
- debt_repayment → achieved
- spending_limit → over_limit only (no achieved)

---

## Mascot Integration

Events:

- DebtIncreased → Dejected
- MilestoneReached → Celebrating

States:

- Dejected (new)
- Celebrating (existing)

Triggers:

- new debt → Dejected
- debt cleared / goal achieved → Celebrating

---

## Security

- A: tenant + member scoped
- B: tenant scoped
- settlement restricted to participants
- no cross-tenant derivation

---

## Consequences

### Positive

- clean debt semantics
- Splitwise + Monarch hybrid model
- goal-driven financial feedback
- mascot becomes meaningful

### Negative

- multi-domain coordination cost
- strict consistency requirements
- additional API + schema surface

---

## Migration

- A/B independent rollout
- no change to existing expense ledger
- derive layer only

---

## Verification

- net balance correctness vs manual
- settlement clears correctly
- liability payments reduce balance
- tenant isolation enforced

---

## Notes

- no asset / investment model
- no full balance sheet
- MONARCH_INSPIRED_UI remains constrained

---

## Index

ADR-0049
Next: ADR-0050
