+++
schema_version = 2
id = "0057"
title = "请求幂等的稳定首次结果与单事务 claim"
summary = "同一意图只提交一次，并在当前授权成立时重放最小稳定首次结果"
current_scope = "服务端 mutation 的 idempotency key、principal binding、事务 claim、结果 envelope 与 retention"
date = "2026-07-10"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "data-consistency"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "后端一致性与协议维护者"
verification_owner = "独立 PostgreSQL 并发 reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0042"
scope = "current-state replay、持久 stale in-progress 与 reclaim 语义"
+++
# 0057 请求幂等的稳定首次结果与单事务 claim

## [ADR-0057-SCOPE] Context, Scope and Non-goals

[[0042]] 已区分 OCC 与幂等，但当前实现仍会按资源最新状态重建 HIT、允许已提交 `in_progress` 在超时后被 reclaim，且记录未绑定原始 principal/device。响应丢失、第三方插写或跨主体 key 碰撞因此可能产生重复副作用、错误 OCC token 或信息泄漏。

本 ADR 约束服务端 mutation；客户端 write-ahead intent、payload version 和 binding exit 由 [[0069]] 负责。

## [ADR-0057-ASSUMPTIONS] Assumptions and Applicability

- PostgreSQL 唯一约束和事务是 claim 权威；不引入独立 lease/fencing 系统。
- key 由客户端在首次发送前持久化，同一业务意图重试复用同一 key。
- validation、权限、OCC 与 5xx 失败不作为成功结果缓存。

## [ADR-0057-DRIVERS] Decision Drivers

- committed-but-unseen 不得二次执行。
- replay 不得借最新资源状态跨过原本应发生的 OCC 冲突。
- idempotency key 不是 bearer；当前权限与原始主体绑定始终优先。
- retention 必须覆盖客户端重放窗口并有真实 sweep。

## [ADR-0057-ALTERNATIVES] Alternatives

- **A. HIT 返回资源当前状态**：结果会随第三方写漂移，拒绝。
- **B. 单独提交可回收 `in_progress` lease**：需要 generation/fencing 与崩溃协议，拒绝。
- **C. claim、业务 mutation、首次结果同一事务提交**：选定。
- **D. 缓存完整 HTTP 成功/失败响应**：扩大 PII、兼容和权限面，拒绝。

## [ADR-0057-DECISION] Decision

### [ADR-0057-C01] replay 只返回最小稳定首次结果且重新授权

成功事务保存版本化 `committed-success` envelope，字段仅允许 status、operation、有限 result kind、必要的不可变 resource reference 和首次 `post_row_version`，序列化 UTF-8 不超过 8 KiB。禁止保存完整资源、请求体、姓名、备注、图片路径、token 或任意扩展袋。

记录在 envelope 外绑定 ledger、account/principal、device/client 与请求 fingerprint。每次 HIT 在暴露 key 命中或 locator 前重新执行当前 authn/authz，并要求原始 binding 匹配；撤销、降权、跨账本或跨 actor 按稳定 401/403/404 拒绝。需要最新资源时只能另列 `current_resource`，后续 OCC 仍使用首次 `post_row_version`。

### [ADR-0057-C02] claim、mutation 与结果在一个 PostgreSQL 事务

同一事务插入 key、执行业务 mutation、写 stable envelope 并提交。竞争事务可在唯一约束等待：首事务提交后 replay，回滚后重新 claim。正常路径不得持久留下可自动 reclaim 的 `in_progress`；发现历史异常行时 fail closed 并走显式 repair，不能让两个请求抢占。

### [ADR-0057-C03] retention 与删除同生命周期

服务端 retention 必须大于客户端最大未解决 outbox age，并只 sweep `succeeded AND expires_at < now`。key 与 envelope 同时删除；主体删除/脱敏优先于剩余 replay 窗口。日志和指标只记录低基数结果、删除数和年龄，不记录 key、payload 或 envelope。

## [ADR-0057-CONSEQUENCES] Consequences

- Good：同一意图恰好提交一次，重放不漂移、不越权。
- Costs：schema 需保存版本化 envelope/binding，路由必须在 commit 前形成稳定结果；同 key 并发可能有界等待。
- Limits：这是稳定操作结果，不承诺逐字节 HTTP replay；数据库不可用时仍不能提供幂等保证。

## [ADR-0057-REVERSIBILITY] Reversibility, Replacement and Retirement

envelope 可新增显式 schema version 或进一步收窄，但不得回到 current-state replay、无 principal binding 或非原子 stale reclaim。若未来选择独立 lease，必须新 ADR 证明 fencing、owner crash 与迁移。

## [ADR-0057-EVIDENCE] Verification and Evidence

- PostgreSQL 双连接并发：相同 key 只产生一次业务副作用，第二个请求重放首次 envelope。
- 在 mutation 前后 rollback、COMMIT 后丢响应和第三方插写：重试分别可重新 claim或返回原始 `post_row_version`，不得二次写或返回最新版本。
- mutation probe 删除 principal/device binding、恢复 stale reclaim 或加入 8193-byte/PII 字段时，测试与数据库约束必须失败。
- 当前 `backend/app/models/idempotency.py` 与 `services/idempotency.py` 未保存稳定 envelope/binding且允许 reclaim，因此状态保持 `nonconformant/failed`。

## [ADR-0057-REFERENCES] References

- [[0042]]：离线重放、OCC 与幂等的基础边界。
- [[0069]]：客户端 write-ahead intent 与 mixed-version binding。
- [PostgreSQL transactions](https://www.postgresql.org/docs/current/tutorial-transactions.html)
