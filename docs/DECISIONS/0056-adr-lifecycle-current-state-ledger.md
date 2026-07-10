+++
schema_version = 2
id = "0056"
title = "ADR 历史与实施状态分离"
summary = "保留不可改写的决定历史，并把当前实施状态与 lineage 单独维护"
current_scope = "仅保留历史真实性原则；双状态账本和旧 registry 机制已由 0065 取代"
date = "2026-07-10"
decision_status = "superseded"
implementation_status = "implemented"
verification_status = "stale"
decision_type = "governance-calibration"
risk_level = "standard"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "架构治理维护者"
verification_owner = "独立 ADR reviewer + CI"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "supersedes"
target = "0039"
scope = "以持续状态账本替代一次性 ADR 实施快照"

[[relations]]
kind = "informational"
target = "0065"
scope = "0065 已取代本 ADR 的状态模型、registry 与机器治理机制"
+++
# 0056 ADR 历史与实施状态分离

## [ADR-0056-SCOPE] Context, Scope and Non-goals

早期 ADR 把“当时为何决定”和“代码今天做到哪里”混在同一正文，[[0039]] 的一次性校准又会过期。本 ADR 曾建立独立状态账本；现行机制已由 [[0065]] 接管，本文件只保留历史不可伪造原则。

## [ADR-0056-ASSUMPTIONS] Assumptions and Applicability

- Git 保存原始决定与后续 successor 谱系。
- 代码与证据会变化，历史 Decision 不应随实现进度重写。
- 本 ADR 的旧双状态枚举和手写状态表不再裁决当前 registry。

## [ADR-0056-DRIVERS] Decision Drivers

- 过时正文不能拖住已明确的新方向。
- 真实代码缺陷也不能靠降低历史要求变绿。
- 决策、实现和验证证据必须可分别审查。

## [ADR-0056-ALTERNATIVES] Alternatives

- **A. 持续重写旧 ADR**：会伪造历史，拒绝。
- **B. 周期性再写全量快照 ADR**：仍会过期，拒绝。
- **C. 冻结决定本体，另维护当前状态并用 successor 改方向**：选定；现由 [[0065]] 完整实现。

## [ADR-0056-DECISION] Decision

### [ADR-0056-C01] 历史决定不得被实施进度倒灌改写

accepted/rejected 决定的上下文、选项、Decision 与 Consequences 保持历史真实性。语义变化必须由 `amends`、`refines` 或 `supersedes` 承担；实现进度、校准和验证证据放在可更新表面，不制造“当时就完全正确”的假历史。

### [ADR-0056-C02] 当前状态机制由 0065 独占

本 ADR 曾定义的双状态账本、手写索引和旧 audit lane 已退役。当前决策/实现/验证三状态、front matter、稳定 clause、legacy ratchet 和生成视图只由 [[0065]] 裁决；不得恢复第二套状态权威。

## [ADR-0056-CONSEQUENCES] Consequences

- Good：保留为何决策，同时允许当前实现被诚实校准。
- Costs：维护者必须沿 lineage 查当前决定，不能只读旧标题。
- Limits：本 ADR 不再定义现行 schema 或工具行为。

## [ADR-0056-REVERSIBILITY] Reversibility, Replacement and Retirement

旧状态账本和 registry 已由 [[0065]] 替代，可删除其消费者；历史真实性原则不可回退。任何治理工具替换仍须先迁移当前状态与关系，再退役旧生成物。

## [ADR-0056-EVIDENCE] Verification and Evidence

- registry 应显示 0056 为 `superseded/stale`，并显示 [[0065]] `supersedes` 0056。
- release audit 不得再发现旧 `_audit_adr_registry.py` lane 或把手写状态表当机器权威。

## [ADR-0056-REFERENCES] References

- [[0039]]：已失效的一次性实施校准快照。
- [[0065]]：现行可执行 ADR 契约与渐进治理。
