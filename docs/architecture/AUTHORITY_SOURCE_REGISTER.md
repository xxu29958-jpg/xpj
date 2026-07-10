# 小票夹全系统权威源登记表

本表回答“正常写入、冲突或损坏时信谁”，只汇总 accepted ADR 与当前代码证据，不自行产生架构决定。
`online authority` 不等于 `recoverable`，PostgreSQL 权威也不等于一张表中两个字段天然一致。

- Catalog version: `1.1.0`
- Reviewed code baseline: `0f1092e625b376d0fa8d4abc214cdc53de93a96d`
- Installer overlay: uncommitted `codex/release-hardening-installer-lifecycle`, listed separately and never counted as main
- Product boundary: [[0066]]

## 登记规则

- PostgreSQL 是结构化账务事实、权限、状态机和引用关系的唯一在线数据库；客户端/文件/备份不能反写推翻它。
- 若同一语义在 PostgreSQL 内有两个可变表示，本表必须标出一致性协议，不能用“都在 PG”掩盖双源。
- 收据附件只有 `PG ownership/lifecycle/expected digest + matching normalized bytes` 同时成立才有效；任何一方都不能
  在冲突时自动获胜。缩略图不是权威。
- Room confirmed 数据是缓存；Room outbox 是本设备未提交意图。两者的销毁权限不同。
- 候选恢复副本只有在隔离环境通过 schema、身份、财务汇总和附件 manifest 后才能晋升。
- `Current state` 是当前代码校准，不是目标。`nonconformant` 不能靠降低本表措辞消除。

## 账本、身份与财务事实

| ID | 语义与在线权威 | 允许写入者 / 约束 | 冲突或损坏裁决 | Current state |
| --- | --- | --- | --- | --- |
| AUTH-ACCOUNT-001 | `Account` 是人/家庭主体；`Device` 是 account 的客户端身份；有效 session 还必须绑定 ledger/scope | identity service；token/device/account/membership 每次请求复核 | 客户端 display/account cache 不得创建身份；disabled/revoked 服务端状态胜 | partial：主体分离已实现，恢复/clone sanitation 未闭环 |
| AUTH-LEDGER-001 | 账本隔离以 `Ledger.ledger_id` 为权威；唯一 active `LedgerMember(role=owner)` 是 owner capability 的 canonical source，`Ledger.owner_account_id` 仅是受约束兼容投影 | ledger/invitation service 同事务更新；DB 强制每账本恰有一个 active owner 且投影一致 | 无 owner、双 owner 或投影漂移均是 integrity incident；owner-only 读写 fail closed，不能任选一个字段继续 | **nonconformant**：尚无 DB 级唯一 active owner/双表示一致性约束；不同消费者仍读取不同来源 |
| AUTH-RBAC-001 | 当前 ledger capability 来自有效 app/Web principal + active `LedgerMember.role`；admin/upload/recovery 不是 member role | `permission_service` + route/service ledger scope；[[0068]] | loopback、Host、Cloudflare Access、OS admin 或隐藏按钮不能替代应用授权 | **nonconformant**：public-admin escape hatch 与 Owner Console 隐式 owner 待迁移 |
| AUTH-EXPENSE-001 | `Expense` 当前行是该账务记录的在线权威状态；amount/currency/time/status/items/splits 有各自约束 | 后端 expense service + DB CHECK/FK/OCC；自动化仅写 pending ownership | Room/UI/CSV/图片/OCR 不得覆盖；确认后当前实现仍允许授权用户原地更正，不能冒充 append-only fact | partial：核心权威成立；更正/reversal/audit 模型尚未明确，退款事实缺失 |
| AUTH-DEBT-001 | `Debt` 是母对象；Repayment/Adjustment/Forgiveness/Void 是余额/终态事件；投影应可由母对象+events 重建 | debt service、positive/signed amount 约束、OCC/locks | 可变 `Debt.status` 与 event fold 不一致时 fail closed 并 repair，不能只信 status | **nonconformant**：rebuild 仍以 mutable status 作 void latch 且排除 DebtVoid |
| AUTH-PLAN-001 | Budget/Goal/IncomePlan/RecurringRule 等是可修订计划/配置事实，不是已发生流水 | 对应 backend service + ledger role/OCC | 报表/AI suggestion 不能反写；历史计划语义改变需版本/审计 | partial：结构化权威成立，部分 version/audit/rebuild 仍缺 |
| AUTH-CATALOG-001 | Category/Merchant/Tag/Rule 是账本范围的分类/解释配置；历史 Expense 字段仍是该行当前值 | catalog/rule/tag services；merge/rename/soft delete 协议 | 目录变化可改变投影解释但不得静默改金额或伪造历史来源 | partial：merge/undo/ABA 和 mixed-version 待收口 |
| AUTH-AUDIT-001 | `LedgerAuditLog` 等业务审计行记录 actor/action/result；运行日志/指标只作运行证据 | 服务端审计 service；敏感字段 allowlist | 日志不能修复业务事实；审计缺口标 incident，不从 UI/cache 补造 | partial：append-only 主要为 service 约定，retention/DB 写权限未统一 |
| AUTH-PROJECTION-001 | stats/report/dashboard、items_sum_status、debt status、图表和搜索索引是派生投影 | 后端 projection/fold；客户端只显示 | 与权威 facts 不一致时丢弃重建或进入 repair；不得让投影反写事实 | partial：部分 disaster rebuild/repair 命令缺失 |

## 图片、AI、凭证与本地状态

| ID | 语义与在线权威 | 允许写入者 / 约束 | 冲突或损坏裁决 | Current state |
| --- | --- | --- | --- | --- |
| AUTH-RECEIPT-001 | 有效附件 = PG 中 ledger/expense ownership、生命周期、expected SHA-256 + 私有存储中匹配的**规范化收据 bytes**；不是用户上传前原始字节 | file/expense service 先解码、去元数据/重编码并生成随机相对路径 | PG 有引用但 bytes 缺失/摘要不符 = degraded integrity；bytes 无引用 = 保护窗后的 orphan candidate | **nonconformant at main**：读取不重验 hash，DB/bytes 无同代 manifest；缺图保留状态修复仅在当前未提交 ADR worktree |
| AUTH-THUMB-001 | 缩略图是从规范化收据图生成的可重建缓存 | thumbnail service；客户端 HTTP/image cache 可再次丢弃 | 缺失/损坏直接重建，不影响收据或账务事实 | implemented for derivation，恢复/清理观测仍 partial |
| AUTH-AI-001 | OCR/AI/规则输出是带 provider/model/parser/provenance 的 suggestion/fact；字段 ownership 与人工命令裁决是否进入 Expense/Plan | provider adapter 只能写允许的 pending/suggestion/fact；用户写移除自动 ownership | 已确认/用户修改字段胜；provider response 永不直接成为余额/预算权威；原图 vision 当前 local-loopback-only，远程原图需独立 accepted 隐私/安全决定 | partial：核心人工确认成立；parser version、逐 provider egress/retention 实现证据仍缺，Budget Advisor allowlist 不授权视觉 provider |
| AUTH-SIGNING-001 | `app_meta` 中 CSRF/audit 等服务端 signing identity 是同一 installation 的持久安全身份 | identity/security service 原子 get-or-create/rotate；明文不出受保护 runtime | same-install restore 保留；clone 必须换新并以 keyed fingerprint 证明不同；有效 override 存在时不能只轮换被遮蔽值 | partial/nonconformant：持久 key 已有，clone/effective-secret 原子证明未闭环 |
| AUTH-BEARER-001 | AuthToken（含 app/admin/Web session）与 UploadLink 的 hash、principal/device/ledger binding、expiry、revocation 由 PostgreSQL 裁决 | identity/session/upload-link service；明文仅签发端短暂出现 | revoked/expired/binding-invalid 服务端状态胜；same-install restore/clone 均不得让备份中的 active bearer 复活 | partial/nonconformant：日常校验大体存在，restore sanitation 与 clone verifier 缺失 |
| AUTH-ONESHOT-001 | Invitation、PairingCode、bootstrap consumption/claim receipt 等一次性能力的 consume/revoke/expiry 状态由 PostgreSQL 裁决 | 对应 claim service 在同事务消费并保存稳定结果；恢复只识别原 operation | 旧备份不得把 consumed/revoked 状态改回 active，也不得重设 expiry；committed-but-unseen 只能返回原 claim 结果 | **nonconformant**：overlay bootstrap recovery 可延长 UploadLink/pairing 有效期，完整 mutation inventory 未证明 |
| AUTH-OPERATOR-001 | `ADMIN_TOKEN`/`APP_TOKEN` 等 operator override 是 effective signing/bearer 输入；HTTP bootstrap secret 只是短命 backend-readable challenge，不是恢复根 | installer/operator 受保护配置写入；backend 只获得运行所需最小值，完成 ceremony 后关闭/轮换 | restore 不得用旧 `.env`、SCM argv 或备份覆盖较新 operator epoch；clone 全部换新 | partial/nonconformant：override 优先级存在，版本/epoch、sanitation 与安全输入仍未闭环 |
| AUTH-RECOVERY-001 | 独立 sealed recovery root/epoch、owner re-enrollment material、handoff 和 rollback/recovery manifest 属于 SYSTEM/Administrators/recovery operator 域，不随 PG generation 回滚 | 持机器锁的短命提权 helper/恢复工具；只能为 canonical owner 签发一次短 TTL re-enrollment capability | backend/PG 账户不能读、写、删、改名或替换；缺 root、epoch/generation 不符或 owner invariant 失败即保持 listener 关闭 | **nonconformant**：主线无独立 recovery principal；overlay 子文件 ACL 被 backend 对父 `app` 目录的 FullControl/`DELETE_CHILD` 破坏 |
| AUTH-OUTBOX-001 | Room `pending_mutations` 是该设备/ledger binding 尚未确认提交的本地意图权威；提交后 PG 结果胜 | repository/outbox engine，Screen/VM 不直接 IO | unknown version、过期、binding/currency/time revision 不兼容时 quarantine/conflict，禁止猜执行 | **nonconformant**：Room 10→11 与 logout/switch 可静默清除 intent |
| AUTH-CACHE-001 | Room confirmed、Web/PWA 静态 cache、内存 DTO 和乐观 UI无独立业务权威 | repository/sync adapter | 与 PG 冲突时丢弃/重拉；旧缓存不得生成权限、换算或状态转换 | implemented in principle；真实 Room rebuild/mixed-version 证据不足 |

## 宿主、安装、恢复与发布物

| ID | 语义与在线权威 | 允许写入者 / 约束 | 冲突或损坏裁决 | Current state |
| --- | --- | --- | --- | --- |
| AUTH-INSTALL-001 | installed release identity 由受保护 release config + SCM argv/account +路径/ACL + DB identity + lifecycle receipt 共同证明；registry 单项不是权威 | installer/UAC helper 持机器锁写入；Manager 只经同一 adapter | 任一证据不一致 fail closed/repair，不能用目标默认值猜 N-1 | main not-started；installer overlay **nonconformant** 于复制边界持久化，以及 handoff/recovery marker 父目录授予 backend 删除/替换能力 |
| AUTH-CONFIG-001 | 账务语义 binding（schema/currency/timezone/identity）必须持久化；调优配置可来自受保护 runtime config/env | config/migration service；语义改变走 migration/revision | env 与持久 binding 冲突 fail closed，不能按 env 重解释历史整数/日期 | nonconformant：home currency/accounting timezone 仍主要是 env/request |
| AUTH-BACKUP-001 | dump/uploads/config/manifest 只是候选恢复集，必须有同代 generation 和校验 | backup/installer/owner maintenance | 缺图片/身份/schema 或隔离 restore 失败时不得切换；`pg_restore --list` 不是恢复证明 | nonconformant：主线仅浅 archive 校验，uploads 独立 mirror，offsite 未加密默认行为需移除 |
| AUTH-RUNTIME-001 | SCM/process/listener/health 是运行证据；backend build/schema/data root attestation 才能证明预期实例 | host adapter/service manager | `health=ok`、同名进程或端口占用不能授权数据/安装操作 | partial；installer overlay 有更强 process proof，主线只具最小 health |
| AUTH-BUILD-001 | 发布物由 Git source + 锁定 toolchain/deps/vendor + immutable staged inputs +最终 artifact hash/attestation 标识 | release build lane | point-in-time manifest/版本字符串不能证明上游真实性或最终产物 | main not-started；overlay 有本地 build receipt 且 real-build workflow 已配置，但无对应 cloud run/clean VM 证据，故仍 unverified；签名与上游真实性未成立 |

## 跨存储附件状态机

| 状态 | PG metadata | normalized bytes | 允许行为 |
| --- | --- | --- | --- |
| complete | 引用、digest、未删除 | 存在且 digest 匹配 | 鉴权读取、配套备份、受控清理 |
| deleted + purge-not-due/pending | 显式 deletion marker/代次、undo deadline 与 purge 状态 | 可以仍存在 | 新读取拒绝；到期后幂等 purge，存在不等于 orphan 或隐私擦除完成 |
| deleted + purge-failed | deletion marker 与失败 receipt | 可能部分/全部仍存在 | 告警、重试、披露残余；不得报告物理删除成功 |
| deleted + purged | deletion marker 与可核验 purge receipt | 在线 normalized bytes 不存在 | UI 可称在线副本已物理清理；备份/旧 generation 是否擦除仍单独证明 |
| missing-or-corrupt | 有引用、无删除标记 | 缺失或 digest 不符 | 标 degraded、拒绝伪造/自动清引用、从同代恢复集 repair |
| orphan | 无有效引用 | 存在 | containment + 保护窗口 + generation 对账后才可删除 |
| restoring | restore manifest 有 | 正在恢复/待核对 | 暂停或隔离写；全量引用/hash 对账后开放 |

## 修改规则

新增存储、provider、sidecar、cache 或凭证时先由 ADR 决定权威/写权限/失败语义，再更新本表。若本表与代码或
accepted ADR 冲突，本表立即降级为 stale 并发起实质审查；禁止用本表反向生成或合法化架构。
