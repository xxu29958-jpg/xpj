+++
schema_version = 2
id = "0076"
title = "Windows installation owner 短期配对与旧协议退役边界"
summary = "提权安装器只提交机器安装事务和短期配对能力，普通用户进程自行建立并保存用户凭据，旧 handoff 永不成为新版权威或门禁"
current_scope = "正式 Windows Inno 首装、repair、跨 release 同事务恢复、installation owner claim、pairing-only handoff、Desktop Manager 首次绑定、旧 owner handoff 审计与统一失败证据"
date = "2026-08-09"
decision_status = "accepted"
implementation_status = "partial"
verification_status = "unverified"
decision_type = "security-identity"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "Windows installer adapter + identity service + Desktop Manager 维护者"
verification_owner = "独立 Windows clean-machine reviewer"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0063"
scope = "ADR-0063-C01 至 C06 在正式 Windows 安装器中的用户凭据派生、恢复与交接方式"

[[relations]]
kind = "amends"
target = "0074"
scope = "ADR-0074-C01 至 C03 的 owner handoff 内容、单文件状态机与 legacy 协议退役语义"

[[relations]]
kind = "depends-on"
target = "0062"
scope = "机器生命周期锁、安装回执、失败补偿与 exact operation 事务边界"

[[relations]]
kind = "depends-on"
target = "0065"
scope = "旧 ADR 不改写、后继修订、clause 证据与 exact-head 发布门"

[[relations]]
kind = "refines"
target = "0068"
scope = "安装机器身份、家庭 owner、短期 pairing child 与用户桌面 session 的信任边界"
+++
# 0076 Windows installation owner 短期配对与旧协议退役边界

## [ADR-0076-SCOPE] Context, Scope and Non-goals

旧 Windows 首装流程让提权 Inno/PowerShell 获得 admin token、upload key 等用户长期 bearer，并把它们写入
机器 handoff。真实安装演练又证明，跨 release repair 会把旧 PENDING、旧 handoff 或 C07 目录当成当前
候选的权威门禁，造成已知旧版本状态永久锁死新版。两者分别违反 Windows 的 machine/user 权限边界和
通用安装器的版本化恢复边界。

本 ADR 只裁决正式 Windows 分发所需的 installation owner 建立与交接。旧 ADR、候选、脚本、回执和
失败样本保留为不可改写审计对象；它们不是当前语义的授权来源。本 ADR 不施工 C02/C03 业务域，不改变
家庭财务事实，不宣称无人值守安装、多实例、代码签名或 N-1 二进制降级已经完成。

## [ADR-0076-ASSUMPTIONS] Assumptions and Applicability

- 当前正式拓扑是一台 64 位 Windows、一套 HKLM/Inno 安装身份、两项 SCM 服务、一个 PostgreSQL cluster。
- Setup 通常由登录用户双击后经 UAC 提权；若 Setup 被直接以管理员 token 启动，Inno 不保证能恢复原登录用户。
- installation owner endpoint 只在受保护的短命 bootstrap listener 窗口开放，loopback 本身不是授权证明。
- Desktop Manager 是普通用户进程；它通过 WinCred 保存的 session 只属于调用 `CredWriteW` 的 Windows 登录会话。
- 任一前提变化（多实例、远程安装、企业部署主体、无交互服务账户）都必须先写后继 ADR 并重新验证。

## [ADR-0076-DRIVERS] Decision Drivers

- 管理员安装器负责 machine-wide 文件、ACL、SCM、数据库和安装事务，不应写入某个用户的设置或长期凭据。
- 崩溃重试必须延续原 operation ID；生成新 operation 不构成恢复。
- PostgreSQL 中的 owner claim、secret consumption、pairing child 和身份行不能半提交。
- 两个独立文件的顺序更新不是原子事务；当前 handoff 必须只有一个原子发布对象。
- 旧协议需要留给审计和显式退役，但不能读取后再反向授权或阻断新版。
- 用户错误、日志和最终证据必须使用同一个稳定 support code 与 operation identity，且不得泄密。

## [ADR-0076-ALTERNATIVES] Alternatives

- **A. 继续由提权安装器创建并保存 admin/upload/session 凭据。** 拒绝。WinCred 按调用 token 的登录会话写入，
  提权 Setup 不能把管理员 token 的 credential set 冒充为原用户；Inno 的 administrative install mode 也要求
  per-user 设置由应用自己完成。
- **B. 每个 release 遇到旧 PENDING 就创建新 operation。** 拒绝。它丢失原 fresh intent 的因果关系，留下
  多个无法裁决的半安装事务。
- **C. 继续使用 `owner-bootstrap.txt` + `owner-handoff-pending` 双文件。** 拒绝。任一发布顺序都有断电窗口，
  下一次 repair 无法只靠“两边不一致”区分自己的 prepared state 与 foreign state。
- **D. installation claim + 短期 pairing child + 单文件 handoff。** 选定。机器事务只携带短期能力，用户
  Manager 自行完成长期身份，DB 和文件崩溃状态均可有限枚举。

## [ADR-0076-DECISION] Decision

正式 Windows 安装器只建立持久 installation owner claim 和短期 pairing child；用户长期身份只能由普通用户
Desktop Manager 消费 pairing 后写入该用户自己的 WinCred。旧 handoff 协议只观察、不消费、不迁移、不阻断。

### [ADR-0076-C01] Machine installer 与 user credential 边界

Inno/提权 PowerShell 允许写 Program Files、ProgramData、HKLM、SCM、PostgreSQL schema、安装 identity 和
受保护 transaction receipt。它们不得接收、显示、复制、落盘或记录 admin token、upload key、desktop
session token 等用户长期 bearer。

安装完成后，Setup 必须先释放 Manager maintenance gate、DataRoot guard 和 lifecycle lock，再调用
`ExecAsOriginalUser` 尝试启动 Manager。调用失败不回滚已提交的 machine install，而是给出从开始菜单启动的
明确路径。Manager 消费 8 位 pairing code，完成 backend activation 后，由 Manager 普通用户进程调用
`CredWriteW`；Setup 不代写 per-user WinCred。

### [ADR-0076-C02] Installation owner claim 是单事务全局唯一事实

`installation_owner_claims` 以 operation ID 为主键，并对 installation ID、active secret hash、pairing child
建立唯一约束。创建 owner account、ledger、membership、bootstrap device、secret consumption、pairing child
和 claim 必须在同一个 PostgreSQL 事务中；任一异常整体 rollback。存在 foreign claim 或既有长期 token 时
返回 `bootstrap_already_initialized`，不能另建第二 owner。

HTTP 响应只含 contract、operation/installation ID、公开 owner/ledger/device 投影、pairing code、expiry、
derivation index 和 claim generation。长期 bearer 出现在响应即为发布阻断。

### [ADR-0076-C03] Recovery 保留 operation，换代只发生在 child

同一 operation ID、installation ID、request fingerprint 和 active secret 的重试必须重放同一未过期 pairing
child。child 过期或受控暴露时，在同一事务中撤销旧 child 及其精确 descendant，写入 replacement secret
consumption，创建下一 child 并递增 generation；operation/installation ID 不变。

operation、installation、request fingerprint、secret hash、claim 关系或 child 关系任一不匹配都 fail closed。
不允许用当前 release fingerprint、用户名、SID、盘符或 C07 目录名制造本机特判。

### [ADR-0076-C04] 单文件 handoff 与有限 crash 状态

当前机器 handoff 只有 `installation-owner-handoff-v2.txt` 一个受保护、原子替换文件，字段固定为 schema、
pending state、contract、operation/installation ID、generation、derivation index、pairing code/expiry 和已冻结的
installer owner PID/创建时间。不得另写 confirmed marker；“更新两份文件”不构成事务。

允许的 crash 状态只有：

1. DB 未提交、文件缺失：同一 operation 从头重试；
2. DB 已提交、文件缺失、bootstrap secret 尚在隔离配置：同一请求重放并原子发布同一 child；
3. 文件已发布、bootstrap secret 尚未退役：复读同一文件后完成 secret 退役，不重发 HTTP；
4. 文件由死亡 installer owner 留下：持同一 lifecycle lock 的 repair 验证 operation/installation 后只重绑
   owner PID/创建时间，保留 generation 和 pairing；
5. 完成页已展示并幂等删除文件：缺失表示 installer handoff 已退役，不得解释为 foreign state。若用户尚未
   完成 Manager pairing，可从本机 Owner Console 生成新的短期 pairing child，不恢复旧长期凭据。

文件存在但 schema、绑定、ACL、owner identity 或 UTF-8 形态无效时，当前协议 fail closed 并保留原件。

### [ADR-0076-C05] 旧协议只作审计，不能锁死新版

`owner-bootstrap.txt`、`owner-handoff-pending` 及其旧 DataRoot/installer-state 位置是 retired audit objects。
普通 install/repair 只可对已知路径做 no-follow 类型观察并输出不含内容的 warning；不得打开内容、推导凭据、
迁移、改 ACL、删除、展示、转写为 v2、授权当前 claim，或因其缺失、损坏、目录/reparse 形态阻断新版。

旧敏感材料的删除必须是另一个版本化 retirement 操作：先证明对应服务/DB 身份和 secret 已失效，再显式删除并
保存 sanitized receipt。`-DeleteData` 的完整卸载仍可在已验证删除边界内移除所有已知名称，但不能把旧内容当
成当前安装身份。

### [ADR-0076-C06] 统一错误与证据合同

每个 installer terminal failure 必须生成同一 public receipt schema：support code、lifecycle stage、context、
finalization attempt ID、installation operation/installation ID、retry class、database mutation state、protected log
和 public receipt 路径。Inno UI、PowerShell exception mapping、SCM/DB 动作和最终证据索引必须一致。公开回执、
transcript、进程参数、环境快照和截图不得含 bootstrap secret、pairing code、token、数据库口令或 raw credential。

### [ADR-0076-C07] 发布资格按 exact head 单向推进

候选顺序固定为：受影响目标测试；Windows PowerShell 5.1 安装器专项测试并在存在 PS7 时验证一致语义；稳定
exact head 一次全量门禁；从该 head 构建并哈希真实 EXE；零安装 Windows 首装、受控失败、无人工清理重试、
服务/DB/schema/backend/GUI、升级和不丢数据的 downgrade/拒绝 downgrade 证据。修改任一候选字节后，旧 full
gate 和 EXE 只作审计，不能给新 head 背书；不得重复全量或无界轮询。

## [ADR-0076-FAILURES] Threat and Failure Matrix

| 事件 | 必须结果 | 禁止结果 |
| --- | --- | --- |
| Setup 直接以管理员 token 启动 | 安装成功后提示从开始菜单启动 Manager | 把 admin WinCred 当原用户 WinCred |
| DB commit 后进程死于 handoff 发布前 | 同 operation 重放同一 child | 新 operation、第二 owner、secret 被烧毁 |
| handoff 发布后进程死亡 | 校验单文件并退役临时 secret | 重新调用后端、双文件不一致锁死 |
| 前 installer 活着 | 拒绝接管 | 仅按 PID 文本覆盖 owner |
| 前 installer 已死亡 | 持锁并验证创建时间后原地重绑 | 改 operation/installation/generation |
| pairing 过期 | 同 claim 换代 child 或由已认证 Owner Console生成新码 | 恢复旧长期 token |
| retired artifact 是文件/目录/reparse/损坏 | sanitized warning，当前安装继续 | 打开内容、迁移、删除或阻断新版 |
| pairing/WinCred 保存中断 | Manager recovery slot 幂等续跑；machine install 不伪装用户绑定成功 | token 出现在 argv/log，或删掉可恢复 proof |
| full gate 后代码变化 | 形成新 candidate 并重新走有界顺序 | 沿用旧 exact-head 结果 |

## [ADR-0076-CONSEQUENCES] Consequences

- Good：管理员安装与用户身份分权；同一 operation 可跨 release 恢复；旧协议不再成为永久门禁；用户只需短期码。
- Costs：增加一张 claim 表、一条安装专用 endpoint、单文件 parser、Desktop pairing 与更多 crash-state 测试。
- Limits / residual risk：代码签名、无人值守部署、自动清退 retired secret 和真实 N-1 二进制 downgrade 仍需独立
  验收；risk owner 在 clean-machine E2E 前不接受 `verified` 或可销售结论。

## [ADR-0076-REVERSIBILITY] Reversibility, Replacement and Retirement

数据库 migration 可在没有 claim 行时直接 downgrade；存在 claim 时 downgrade 必须先证明没有任何消费者和 owner
身份依赖，默认拒绝破坏性回退。endpoint 和 v2 handoff 至少保留一个已发布升级窗口的兼容读取。未来协议用新 endpoint、
新 schema 和后继 ADR 迁移；旧文件先停止写入，再证明无消费者，最后通过显式 retirement 删除，绝不回写本 ADR 或旧 ADR。

## [ADR-0076-EVIDENCE] Verification and Evidence

- DB/route：`test_installation_owner_bootstrap.py` 覆盖首次提交、同 operation replay、foreign claim、过期 child 换代、
  collision/异常 rollback；migration 测试覆盖唯一约束与 downgrade。
- PowerShell/Inno：`test_backend_bootstrap_contract.py`、`test_installer_lifecycle_contract.py` 覆盖单文件原子发布、死亡
  owner 接管、PS5.1/PS7 parser parity、retired object 不读取/不阻断、完成页无长期 credential。
- Desktop：`test_product_identity.py`、`test_app_controller.py` 和真实 Windows WinCred/GUI E2E 证明普通用户保存、恢复与
  本机无公网配置时仍可生成/消费 pairing。
- 发布：保存 exact head、full-gate XML、EXE SHA256、PID/子进程树、SCM `QueryServiceConfig`/状态、PostgreSQL system
  identifier/Alembic revision/seed row hashes、failure receipt、protected logs、首装与无清理重试、升级/downgrade 证据。
- 当前 implementation 为 partial、verification 为 unverified；只有同一 exact-head EXE 在零安装 Windows 完成全部演练后
  才能通过后继状态证据标记 verified。

## [ADR-0076-REFERENCES] References

- [[0062]] machine lifecycle transaction；[[0063]] 历史 owner ceremony；[[0074]] 历史 installer-state/handoff；[[0068]] 身份边界。
- [Inno Setup Administrative install mode](https://jrsoftware.org/ishelp/topic_admininstallmode.htm)
- [Inno Setup ExecAsOriginalUser](https://jrsoftware.org/ishelp/topic_isxfunc_execasoriginaluser.htm)
- [Microsoft CredWriteW](https://learn.microsoft.com/en-us/windows/win32/api/wincred/nf-wincred-credwritew)
- [Microsoft CreateServiceW](https://learn.microsoft.com/en-us/windows/win32/api/winsvc/nf-winsvc-createservicew)
- [PostgreSQL transactions](https://www.postgresql.org/docs/current/tutorial-transactions.html)
