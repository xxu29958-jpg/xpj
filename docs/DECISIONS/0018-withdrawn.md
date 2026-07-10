+++
schema_version = 2
id = "0018"
title = "已撤回决定的编号墓碑"
summary = "0018 没有可恢复的决定本体，保持 rejected tombstone 且永不复用编号"
current_scope = "仅保存缺失历史与编号不可复用事实，不产生任何产品或实现契约"
date = "2026-07-11"
decision_status = "rejected"
implementation_status = "not-started"
verification_status = "unverified"
decision_type = "governance-calibration"
risk_level = "low"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "架构治理维护者"
verification_owner = "ADR registry reviewer"
risk_owner = "owner / 项目维护者"
+++
# 0018 已撤回决定的编号墓碑

## [ADR-0018-SCOPE] Context, Scope and Non-goals

早期索引把 0018 标为已撤回，但仓库没有原文、日期或撤回原因。本 ADR 不猜测丢失内容，也不把编号空洞解释成当前架构决定；它只保留“曾有记录且已撤回”的事实。

## [ADR-0018-ASSUMPTIONS] Assumptions and Applicability

- 没有可验证来源能恢复原决定本体。
- 若未来找到原始材料，只能追加来源和勘误；任何新方向仍须使用新编号。

## [ADR-0018-DRIVERS] Decision Drivers

- 决策历史必须可追踪，编号不能静默消失或复用。
- 未知历史应明确保持未知，不能由维护者或 AI 补写。

## [ADR-0018-ALTERNATIVES] Alternatives

- **A. 删除编号**：会制造无法解释的缺口，拒绝。
- **B. 推测并补写原决定**：会伪造历史，拒绝。
- **C. 保留 rejected tombstone**：选定。

## [ADR-0018-DECISION] Decision

### [ADR-0018-C01] 0018 永久不复用且没有现行实现消费者

0018 保持 `rejected`；任何代码、测试、迁移或产品能力不得以它作为当前授权。发现原始记录也不能把该编号改回 accepted，新决定必须另建 ADR。

## [ADR-0018-CONSEQUENCES] Consequences

- Good：编号连续性和历史诚实性得到保留。
- Costs：索引中永久存在一个无实现的 tombstone。
- Limits：本文件不能解释已经丢失的撤回原因。

## [ADR-0018-REVERSIBILITY] Reversibility, Replacement and Retirement

编号墓碑不可退役或复用。若找到原始材料，只能追加可验证来源；任何替代决定使用新编号并建立关系。

## [ADR-0018-EVIDENCE] Verification and Evidence

- ADR gate 必须证明 0018 文件存在、状态为 rejected、编号唯一，且没有 accepted ADR 把它当作有效依赖。
- 全仓搜索不得发现以 0018 为实现授权的生产消费者；发现即停止并人工审查。

## [ADR-0018-REFERENCES] References

- [[0065]]：现行 ADR 状态、稳定条款与编号治理。
