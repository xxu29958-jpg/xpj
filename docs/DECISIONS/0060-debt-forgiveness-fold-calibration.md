+++
schema_version = 2
id = "0060"
title = "Debt forgiveness fold 与事实重建"
summary = "forgiveness 减少 remaining但不增加 paid，DebtVoid 必须进入纯事实灾难重建"
current_scope = "Debt 的 repayment、adjustment、forgiveness、void 余额 fold、终态与投影恢复"
date = "2026-07-10"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "domain"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "Debt 领域维护者"
verification_owner = "独立财务正确性 reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0049"
scope = "forgiveness 的 canonical/as-of fold 与 DebtVoid 灾难重建"
+++
# 0060 Debt forgiveness fold 与事实重建

## [ADR-0060-SCOPE] Context, Scope and Non-goals

[[0049]] 加入 `DebtForgiveness` 后，在线余额已将其视为债权免除，但旧公式和恢复清单没有完整承接；当前 rebuild 又依赖 mutable `Debt.status` 且排除 `DebtVoid`。本 ADR 统一在线、as-of、投影和灾难恢复，不把 Debt 扩展成通用会计总账。

## [ADR-0060-ASSUMPTIONS] Assumptions and Applicability

- repayment 表示实际偿付，forgiveness 表示无资金转手的债权免除。
- event 行是 fold 输入；余额/status 投影可损坏或删除重建。
- fold-changing write 在父 Debt 的 PostgreSQL 序列化边界内执行。

## [ADR-0060-DRIVERS] Decision Drivers

- 同一事实集合只能产生一套余额与终态。
- forgiveness 不能虚增 paid 或还款次数。
- 灾难恢复不能从可变 status、历史响应或 UI cache 猜事实。

## [ADR-0060-ALTERNATIVES] Alternatives

- **A. 只在某个读取路径特判 forgiveness**：其他投影/恢复仍会错，拒绝。
- **B. 把 forgiveness 当 repayment**：污染现金偿付统计，拒绝。
- **C. 所有 remaining fold 纳入 forgiveness，paid fold 排除，并从 DebtVoid 重建终态**：选定。

## [ADR-0060-DECISION] Decision

### [ADR-0060-C01] canonical 与 as-of fold 使用相同事实集合

`paid = sum(valid repayments)`；`remaining = principal + adjustments - valid repayments - forgiveness`。valid repayment 是没有对应 RepaymentVoid 的 repayment。as-of fold 仅增加统一的 `created_at <= cutoff` 过滤，不得换公式。任何写入都重算并拒绝 `remaining < 0`。

forgiveness 不进入 paid、repayment count 或现金流；`remaining == 0` 可 cleared，但 `is_forgiven` 还必须存在 forgiveness fact。撤回 forgiveness 必须追加显式 correction/reversal，禁止删改历史行。

### [ADR-0060-C02] DebtVoid 与余额事件共同构成重建输入

灾难重建只从 Debt、Repayment/RepaymentVoid、Adjustment、Forgiveness、DebtVoid 及必要 linkage/audit 事实生成余额和终态。DebtVoid 重建 `voided` latch，并把债务排除出 outstanding、goal/projection 与自动匹配；不得伪造成 `remaining=0` 或 `paid=principal`。mutable `Debt.status` 只是待校验投影，不能作为 void 输入。

## [ADR-0060-CONSEQUENCES] Consequences

- Good：在线、as-of、报表和恢复共享同一财务语义。
- Costs：新增 fold-changing fact 必须同步更新 fold、projection、rebuild 与 golden tests。
- Limits：本 ADR 不定义完整退款/冲销总账；由 [[0073]] 承接跨事实投影。

## [ADR-0060-REVERSIBILITY] Reversibility, Replacement and Retirement

不能回到漏算 forgiveness 或从 mutable status 重建。未来改变 forgiveness 可逆性时必须新增 correction fact、迁移旧事件并双跑新旧 fold 对账后 supersede。

## [ADR-0060-EVIDENCE] Verification and Evidence

- `principal=100, repayment=30, forgiveness=70` 必须得到 `remaining=0, paid=30, is_forgiven=true`。
- 删除所有可变 projection 后，仅靠上述事实表重建与在线结果逐 debt/ledger 对账一致；重复 repair 幂等。
- 仅有 `Debt + DebtVoid` 时必须重建为 voided 且不进入 outstanding/goal。
- 当前 rebuild 仍以 mutable status 作 latch并排除 DebtVoid，因此状态保持 `nonconformant/failed`。

## [ADR-0060-REFERENCES] References

- [[0049]]：Debt 领域、权限、OCC 与事件基础。
- [[0073]]：财务事实、更正、reversal 与投影矩阵。
- `backend/app/services/debt_service/_fold.py`
