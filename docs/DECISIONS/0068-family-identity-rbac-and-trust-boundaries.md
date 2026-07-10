+++
schema_version = 2
id = "0068"
title = "家庭身份、账本 RBAC 与运行/恢复信任边界"
summary = "分离家庭成员、账本 owner、设备会话、上传入口、维护和恢复权限"
current_scope = "Account/Ledger/Member/Device/session/UploadLink/Web/Owner Console/admin/recovery 的授权与生命周期"
date = "2026-07-11"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "security-identity"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "identity、permission、Web 与宿主安全维护者"
verification_owner = "独立 security/authorization reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "supersedes"
target = "0022"
scope = "当前家庭权限矩阵、owner transfer、UploadLink 与 Web/Owner 信任边界"

[[relations]]
kind = "refines"
target = "0028"
scope = "公开 Web session 与 public admin surface 的最小暴露规则"

[[relations]]
kind = "refines"
target = "0045"
scope = "Web session/CSRF key 与 clone/restore identity 的生命周期"

[[relations]]
kind = "refines"
target = "0059"
scope = "日常凭证、恢复材料、restore 与 clone 的权限隔离"

[[relations]]
kind = "refines"
target = "0063"
scope = "owner bootstrap/recovery ceremony 与日常 intake/onboarding 凭证分离"
+++
# 0068 家庭身份、账本 RBAC 与运行/恢复信任边界

## [ADR-0068-SCOPE] Context, Scope and Non-goals

[[0022]] 的 owner/member/viewer 起点仍有价值，但其当前权限表已经错误：owner transfer 已实现、member 不能管理
UploadLink、`/web` 可以通过 session 从公网访问，只有 `/owner` 固定 loopback。与此同时，当前代码仍允许
`ALLOW_PUBLIC_ADMIN_API=true` 把 `/api/admin/*` 暴露到公网，并让无应用会话的 loopback Owner Console 自动以
数据库中的 owner 身份执行账本业务操作。这混合了家庭 owner、宿主维护者和本机进程三种信任。

本 ADR 定义应用身份、账本角色、凭证 scope、Web/Owner surface 和恢复权限。它不引入邮箱/手机号/第三方登录，
也不假设本机所有进程可信。

## [ADR-0068-ASSUMPTIONS] Assumptions and Applicability

- 当前家庭规模小，但同一主机可有多个普通用户进程、浏览器扩展、隧道 connector 和恶意/失陷服务进程。
- OS Administrator/SYSTEM 可以最终读取本机数据；架构仍通过服务账户/ACL/ceremony 减少日常暴露和误操作。
- loopback peer 只证明网络路径，不能证明家庭账户、账本角色或恢复权限；反向代理也可能以 loopback peer 到达。
- Cloudflare Access 可以增加入口认证，但不替代应用 session、账本 membership、CSRF、OCC 和审计。
- 当前没有商业 IdP；`identity_provider/cloud_subject_id` 只是扩展缝，不授权未实现的云登录。

## [ADR-0068-DRIVERS] Decision Drivers

- 最小权限：上传、日常记账、owner 管理、宿主维护和恢复不共享万能 token。
- 多账本：Account 身份不能自动获得所有 Ledger；每次业务写必须在当前 membership 中重新授权。
- 撤销与 transfer：旧 session、UploadLink、pairing 和恢复 secret 的失效必须可证明，不能靠 UI 隐藏。
- 公网最小面：只公开有真实消费者且能做到应用级鉴权/限流/审计的 endpoint。
- 服务账户失陷不能自动获得 owner/recovery 明文；本机网页也不能静默冒充家庭成员。

## [ADR-0068-ALTERNATIVES] Alternatives

### [ADR-0068-ALT-A] A. 一个 admin token 管所有账本、设备、上传和恢复

拒绝。泄漏 blast radius 覆盖全部财务事实，且无法表达 owner transfer、member/viewer 或恢复隔离。

### [ADR-0068-ALT-B] B. loopback 即 owner，Cloudflare Access 即公网管理员

拒绝。loopback 可被本机进程或 connector 使用；edge 身份不能替代账本角色和 CSRF，也无法审计真实业务 actor。

### [ADR-0068-ALT-C] C. 分离 principal、ledger role、credential scope 与 recovery capability

选定。授权取决于有效 principal + 当前 ledger membership + endpoint capability；宿主/恢复走独立 ceremony。

## [ADR-0068-DECISION] Decision

### [ADR-0068-C01] Account、Ledger、Member、Device 和 credential 是正交身份

- Account 是人/家庭主体；Ledger 是账务隔离域；active `LedgerMember` 是 account 在该账本的角色与 capability 权威。
- Device 属于 Account，不自动属于所有账本；AuthToken 必须绑定 account/device/ledger/scope，使用时重新确认
  account/device/token 未禁用、membership 仍有效、role 满足命令。
- 每个 ledger 恰有一个 active `LedgerMember(role=owner)`；它是 owner 授权和 repair 的 **canonical source**，由数据库
  唯一约束、服务事务和启动/恢复 invariant 共同强制。`Ledger.owner_account_id` 只是受约束的兼容投影，不得独立授权；
  与 canonical membership 不一致时所有 owner-only 写 fail closed。owner transfer 先在同一事务迁移 canonical membership、
  同步投影并写审计，再使旧 owner 的 owner-only capability 立即失效。mixed-version 全部消费者迁完后应删除该投影。
- public ID 是协议身份；内部整数 ID、路径和 hash 不授予权限。

### [ADR-0068-C02] 账本角色只授权应用业务能力

| 角色 | 允许 | 禁止 |
| --- | --- | --- |
| viewer | 读取被授权账本的允许视图/报表 | 创建、编辑、确认、删除、成员/凭证管理 |
| member | viewer + 日常账务命令、受控离线重放 | 成员/owner transfer、UploadLink、恢复/宿主维护 |
| owner | member + 账本策略、成员/邀请、owner transfer、该账本 intake capability | 跨账本、宿主/DB/恢复材料的隐式权限 |

“owner”不是 OS 管理员，“admin”也不是账本 owner。每个 service/route 必须调用 capability guard；ledger filter 是
第二道隔离，不是遗漏授权的替代。

### [ADR-0068-C03] 凭证 scope 和生命周期不得互换

- app session：日常读取/写入，短期 bearer，绑定 account/device/ledger，可撤销/轮换/过期。
- Web session：绑定 account 和当前 ledger，使用 `__Host-` cookie、CSRF、same-site/secure 策略；切账本重新授权。
- PairingCode：短 TTL、一次性、只能换设备 session；失败/重试不枚举 account/ledger。
- UploadLink：单账本、单用途 `create pending draft` capability，有 TTL/撤销/配额/限流；不得读取、确认、列举或管理。
- admin maintenance：诊断/设备/宿主维护的窄 capability；不得作为普通账本业务写的后门。
- bootstrap/recovery：只在受保护 ceremony 中存在；不能从旧 env、SCM argv、备份或服务重启复活。

一次性、长期和恢复凭证必须分别记录生成、明文位置、ACL、传输、消费、轮换、撤销、销毁和 restore/clone 行为。

### [ADR-0068-C04] 公共面只允许应用 session 和 UploadLink 所需入口

支持的公网面是经过应用协议保护的 `/web`、必要 `/api`、配对/登录入口和 `/u/{upload_key}`。`/owner`、
`/api/admin/*`、bootstrap、恢复和宿主控制默认且永久 fail closed 于公网；Cloudflare Access 只能加固已批准入口。

`ALLOW_PUBLIC_ADMIN_API` 不是受支持扩展缝，应移除。未来若有真实远程维护消费者，必须新 critical ADR 设计单独
maintenance principal、MFA/短期授权、设备绑定、命令 allowlist、审计和撤销；不能复用当前长期 admin bearer。

### [ADR-0068-C05] Owner Console 不能把“本机”静默翻译成“家庭 owner”

`/owner` 可以作为 loopback-only 宿主/恢复适配界面，但 loopback + Host 只是一道网络边界。普通账本业务、成员管理、
规则/财务事实变更必须建立明确的 owner application principal，或使用一次性、短期、审计完整的 local-owner ceremony。
禁止从数据库挑一个 owner account 后让任意本机请求以其名义写账本。

[[0059]] 的 recovery principal 是该 local-owner ceremony 唯一允许的无日常 session 入口：它独立于可回滚数据库 bearer，
绑定 installation/generation/recovery epoch，只能为 canonical active owner 签发一次短 TTL re-enrollment capability。它不得
直接获得普通账本写、长期 admin 或跨账本权限；缺失、epoch 倒退或 owner invariant 失败时 listener 保持关闭。

迁移期间，现有 Owner Console 隐式 owner 模式是**明确 legacy exception**：只允许本机、不得公网、动作全审计、不得扩大
消费者，并必须按切片迁到显式 re-auth/capability。它不能成为 Linux/cloud adapter 的接口。

### [ADR-0068-C06] 维护和恢复权限与普通服务账户分离

- backend 服务账户只读其 executable/config 并写 app runtime/data；不得读取、删除、改名或替换 owner handoff、rollback key、
  recovery root、re-enrollment material、密封恢复包或 installer recovery receipt。只收紧子文件 ACL 不够：这些材料的父目录
  也不得给 backend `DELETE_CHILD`/write/full-control。
- PostgreSQL 服务账户只管理 PG data，不读取 uploads/app secret/recovery sibling。
- installer/helper 以短命提权进程使用恢复材料，完成后销毁或密封到 SYSTEM/Administrators-only 域。
- restore/clone 在开放 listener 前校验 installation identity、按 [[0059]] sanitation signing/bearer/one-shot/operator secret，验证
  recovery epoch，并产生审计回执；全量撤销后只能由独立 recovery principal 完成最小 owner re-enrollment。
- Administrator 能强行接管机器是残余风险，不授权应用把恢复材料长期放在宽权限目录。

### [ADR-0068-C07] 权限失败和枚举语义稳定

- 缺/无效凭证为 401；有效 principal 无 capability 为 403；跨账本敏感资源可用 404 防枚举；冲突/转让/状态错误用
  稳定 409 code。不能靠文案区分机器语义。
- PairingCode、UploadLink、token hash 和恢复 secret 不得出日志、命令行、URL 查询、注册表或诊断包。
- 认证/授权失败不能产生业务副作用；限流记录只能使用不可逆 remote key，不保存 bearer。
- UI 只展示当前 principal 真实能力；服务端仍独立检查，隐藏按钮不是授权。

### [ADR-0068-C08] owner transfer、撤销和恢复必须抗并发

owner transfer、token/device revoke、UploadLink rotate、pair consume 和 bootstrap/recovery 使用数据库锁/OCC/唯一约束串行化。
每个命令在写前最后一次复核 principal 和 membership；并发撤销胜出时不得返回可用新明文。恢复同一 secret 不得延长已过期
UploadLink 或重新激活 revoked credential；需要新入口时走显式 rotate，产生新 identity 和审计。

## [ADR-0068-CONSEQUENCES] Consequences

Good：家庭 owner、维护者和恢复主体不再共享万能信任；公网面、UploadLink 和离线 session blast radius 可控；owner transfer
有真实即时语义。Costs：Owner Console 的无会话业务操作和 public admin escape hatch 必须迁移；bootstrap 一次交付多种长期
凭证需拆 ceremony。Residual risk：OS Administrator 仍可最终读取本机数据；本 ADR 的目标是缩小日常暴露和留下证据，不能
宣称防住恶意主机管理员。

## [ADR-0068-REVERSIBILITY] Reversibility, Replacement and Retirement

凭证实现、Web session 或 IdP 可替换，但 account/ledger/device/scope/recovery 分离不能回退。迁移 Owner Console 时先实现并演练
[[0059]] recovery principal + 显式 owner re-enrollment，再逐项关闭隐式 owner；不得用“第一个 Account”继续充当恢复入口。未来云端身份由新 ADR
refine principal proof 和 tenant boundary，不能让 `cloud_subject_id` 自动获得现有账户。

复审触发：需要远程维护、多组织/多租户、OS 多用户共享主机、第三方 IdP、headless Linux、或管理员/恢复事故。

## [ADR-0068-EVIDENCE] Verification and Evidence

- 权限矩阵 route/service test：viewer/member/owner/app/admin/upload/Web/recovery 对每类命令逐项 allow/deny。
- mutation test 删除任一 `require_*` guard 时，service-layer principal/ledger guard 仍拒绝；两层都被测量而不互相冒充。
- 公网 Host + loopback connector 对 `/owner`、admin、bootstrap/recovery 始终拒绝；设置 legacy public-admin env 也不能打开。
- 本机无 owner principal 请求普通账本写必须拒绝；显式 local-owner ceremony 有 TTL、单用途、审计和撤销。
- 直接 SQL 制造两个 active owner、无 active owner 或 `owner_account_id` 漂移：owner-only route、restore 和 repair 全部 fail closed；
  canonical membership 修复后投影才可重建，不能反向用投影覆盖 membership。
- owner transfer 与旧 owner 并发写、token revoke 与请求、UploadLink rotate 与上传、pair consume 并发做 PostgreSQL 实测。
- restore/clone 后旧 bearer/one-shot/CSRF key 按 policy 失效，新 listener 开放前完成 sanitation。
- sanitation 撤销全部日常 credential 后，只有正确 installation/generation/epoch 的 recovery principal 能为 canonical owner 签发
  一次 re-enrollment；重放、跨实例、跨 generation、非 owner 与直接账本写均拒绝。
- Windows overlay 必须以真实 backend 虚拟服务账户证明无法 read/delete/rename/replace handoff、recovery root 和 recovery receipt；
  仅对子文件检查 ACL、但父目录仍给 FullControl 的测试必须失败。
- 日志/argv/env/registry/diagnostic scan 不含 bearer、UploadLink、pairing、bootstrap/recovery secret。

反向验收：任一 public admin 开关可暴露现有 admin bearer、任一本机请求可无 principal 冒充 owner、member 可管理 UploadLink、
恢复可延寿旧 credential、sanitation 后只能依赖隐式 Owner Console 重入，或 backend 服务账户能读/删/替换 owner/recovery 材料，
均证明本契约未成立。

## [ADR-0068-REFERENCES] References

- [[0028]] Public Web session-gated surface。
- [[0045]] CSRF 持久化随机签名 key。
- [[0059]] 持久 secret restore/clone identity。
- [[0063]] 可恢复 Owner bootstrap ceremony。
- [OWASP Authorization Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Authorization_Cheat_Sheet.html)
- [OWASP Session Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Session_Management_Cheat_Sheet.html)
