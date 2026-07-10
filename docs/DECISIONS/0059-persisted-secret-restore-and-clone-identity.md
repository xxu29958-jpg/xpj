+++
schema_version = 2
id = "0059"
title = "持久 secret 的 restore、clone 与恢复主体"
summary = "same-install 保留 signing identity但撤销回滚 bearer，clone 重建安全域，并保留独立 owner re-enrollment 根"
current_scope = "数据库内 key、bearer/one-shot、operator override、recovery root 在 same-install restore 与 independent clone 中的生命周期"
date = "2026-07-10"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "security-identity"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "identity、安全恢复与宿主维护者"
verification_owner = "独立 security/recovery reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0045"
scope = "per-install signing key 的 restore/clone 身份、首次生成与轮换边界"
+++
# 0059 持久 secret 的 restore、clone 与恢复主体

## [ADR-0059-SCOPE] Context, Scope and Non-goals

数据库备份会复制 `app_meta` signing/audit key、token hash 和一次性授权状态；旧备份可能复活后来撤销的 bearer。独立 clone 若沿用数据库外 override，又可能与源实例共享安全身份。仅轮换 signing key 不能撤销 bearer，仅撤销所有 bearer 又会在当前无密码/IdP 的产品中造成 owner 无法重新签发凭证。

本 ADR 定义 secret 分类、same-install、clone 与独立恢复主体；附件同代晋升见 [[0071]]，角色与信任边界见 [[0068]]。

## [ADR-0059-ASSUMPTIONS] Assumptions and Applicability

- PostgreSQL 是身份/授权状态的在线权威，但可回滚备份不是撤销状态的单调权威。
- 当前 Account 没有密码登录；日常再签发依赖有效 owner session 或 pairing。
- OS Administrator 能最终接管机器，但不自动等于家庭 owner；恢复必须有显式 ceremony 和审计。
- 普通 backend/PG 服务账户不得读取 recovery root、clone key 或 owner re-enrollment material。

## [ADR-0059-DRIVERS] Decision Drivers

- 同一安装恢复不得复活备份之后已撤销的能力。
- clone 不得共享 source 的 signing、operator 或 recovery identity。
- 全量 sanitation 后必须仍有最小、可证明的 owner re-enrollment 路径，不能依赖将被退役的 loopback 隐式 owner。
- secret 明文、比较证据和轮换结果不得进入日志、argv、普通诊断或可回滚 manifest。

## [ADR-0059-ALTERNATIVES] Alternatives

- **A. restore/clone 均保留所有 key 与 bearer**：会复活撤销并跨实例共享安全域，拒绝。
- **B. 所有 restore 都轮换 signing key，但保留 bearer**：不能阻止 hash-only bearer 复活，拒绝。
- **C. 全撤销后依靠 loopback Owner Console 冒充首个 Account**：把本机进程当家庭 owner，拒绝。
- **D. 区分 same-install/clone，并以独立 recovery principal 完成最小 re-enrollment**：选定。

## [ADR-0059-DECISION] Decision

### [ADR-0059-C01] 恢复 inventory 分为五类且默认 fail closed

恢复工具必须枚举：一、数据库 signing/audit key；二、session/admin/UploadLink 等 bearer；三、Invitation/Pairing/bootstrap consumption 等 one-shot 生命周期；四、数据库外 operator override；五、独立 recovery root/re-enrollment capability。类别是开放规则，不是表名白名单；新增 credential 模型而无 restore/clone policy 与 mutation test 时发布失败。

### [ADR-0059-C02] same-install 保留 signing identity、撤销回滚授权，再最小重入

same-install 恢复原数据库 signing identity，但在 listener 开放前撤销备份内所有 active bearer/one-shot，保留 revoked/consumed 历史，不从旧配置覆盖较新的 operator secret/credential epoch。恢复后不得声称旧 session、Invitation、PairingCode 或 UploadLink仍有效。

恢复集必须同时携带或引用一个**不随数据库 generation 回滚**的 sealed recovery principal：至少绑定 installation identity、recovery epoch/key id、用途和当前 generation，明文只在 SYSTEM/Administrators/recovery operator 域。验证成功后，它只能签发一次短 TTL、单用途的 owner re-enrollment capability，用于当前 active owner 建立一个新设备/session；不得直接成为长期 admin bearer、跨账本写入口或数据库任意管理权限。消费、失败、轮换和撤销写入单调 recovery receipt。

缺少 recovery root、epoch 倒退、owner canonical invariant 失败或 generation 不匹配时保持 listener/writer 关闭并进入显式人工 adoption；不得回退到“取第一个 Account”、恢复旧 bootstrap secret或开放 public admin。该 recovery root 必须有独立密封备份/轮换协议，否则候选恢复集不能标为可自助恢复。

### [ADR-0059-C03] clone 重建所有实例安全身份

clone 必须生成新的 installation identity、signing/audit key、operator secret 和 recovery root/epoch，撤销全部复制来的 bearer/one-shot，并清除旧 bootstrap/handoff。一次性 verifier 用 keyed comparison fingerprint 证明 source/target 的 effective key 集不同；禁止把 raw/unkeyed secret hash写入 manifest。任一 key 仍相同或 source fingerprint 不可验证时不开放服务。

### [ADR-0059-C04] key 生成、轮换和有效值必须原子可证明

数据库 key 首次生成使用唯一约束的原子 get-or-create，冲突进程回读同一胜者。轮换作用于最终 effective secret，不能只改被环境 override 遮蔽的 `app_meta`。轮换记录 key id/epoch/time/result，不记录 material；旧 key grace 若未来需要，必须新 ADR 且不超过受影响 session 最大寿命。

## [ADR-0059-CONSEQUENCES] Consequences

- Good：恢复不复活旧能力，clone 不共享安全域，sanitation 后仍有最小合法 owner 重入。
- Costs：恢复集多一个必须密封、轮换、演练的 recovery root；restore/clone 需要隔离 verifier 和 re-enrollment UI/runbook。
- Limits：recovery root 与所有管理员控制同时丢失时不能自动恢复访问；必须明确人工 adoption，不能以安全后门换便利。

## [ADR-0059-REVERSIBILITY] Reversibility, Replacement and Retirement

key store、密封机制和 re-enrollment transport 可替换，但 same-install/clone 隔离、撤销不复活及独立 recovery principal 不可回退。替换 recovery root 时先双读验证新旧 epoch、签发并消费测试 capability，再撤销旧 root；旧 generation 永远不能降低 epoch。

## [ADR-0059-EVIDENCE] Verification and Evidence

- same-install：恢复旧备份后 signing key 保持，备份内所有 active bearer/one-shot 失效；独立 recovery capability 只能为 canonical owner 签发一次短期 re-enrollment，消费后重放失败。
- clone：effective signing/audit/operator/recovery fingerprints 全部与 source 不同，旧 token/link/code/bootstrap/handoff 均不可用。
- mutation inventory：新增任何 token-hash/one-shot 模型而无 handler 时 gate 失败；删除 Invitation 或 operator override sanitation 时 restore drill 失败。
- 服务账户负测：backend/PG 账户不能读、删、改名或替换 recovery root/re-enrollment material；SYSTEM/Admin helper 可在持锁 ceremony 中使用。
- 当前主线没有 sanitation、独立 recovery principal、clone verifier 或同代晋升，旧 runbook还期望恢复后 token 有效，因此保持 `nonconformant/failed`。

## [ADR-0059-REFERENCES] References

- [[0045]]：CSRF signing key 的持久随机性与 fail-closed。
- [[0068]]：canonical owner、日常权限和恢复信任边界。
- [[0071]]：DB 与附件同代候选恢复集。
- [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html)
