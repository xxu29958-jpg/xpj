+++
schema_version = 2
id = "0062"
title = "Windows 安装事务：生命周期回执、复制边界与恢复协议"
summary = "用机器锁、持久回执和复制边界区分可补偿失败与必须 repair 的故障隔离"
current_scope = "Windows 安装/升级/修复/卸载生命周期；main 基线未实现，installer overlay 仍有未持久化复制边界和非原子恢复标记"
date = "2026-07-10"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "deployment-runtime"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "Windows 安装器维护者"
verification_owner = "独立安装/恢复 reviewer + clean-machine CI"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0047"
scope = "安装数据/升级、启动验收和生命周期实施叙述"

[[relations]]
kind = "depends-on"
target = "0041"
scope = "PostgreSQL-only、Alembic、pg_dump/pg_restore 与 schema compatibility"

[[relations]]
kind = "informational"
target = "0006"
scope = "Windows PowerShell 5.1 编码与脚本运行边界"
+++
# 0062 Windows 安装事务：生命周期回执、复制边界与恢复协议

## [ADR-0062-SCOPE] Context, Scope and Non-goals

[[0047]] 选定了 Inno Setup、PostgreSQL/后端双 Windows 服务、独立虚拟服务账户和
`ProgramData` 数据根，但没有定义一次安装、修复或升级在崩溃与重试下的事务边界。
审查必须同时区分两个事实层：`main@0f1092e625` 仍是旧的 best-effort 安装脚本，没有机器级锁、
四模式、生命周期回执或复制前事务；`E:\projects\xiaopiaojia` 的未提交 installer overlay 已加入
release config、机器锁、受保护回执、复制前旧版本校验、升级快照和复制后修复标记。overlay 是
待验证的候选实现，不是主线证据。若混写这两个基线，既会掩盖 main 的缺口，也会把“组件存在”
误写成“跨进程、断电下的安装事务已经成立”。

本 ADR 固化**当前代码方向**。它不把未提交 overlay 冒充 main，也不把尚未实现的版本化程序目录、
自动数据库恢复或干净机 E2E 倒灌成虚假已完成项。

## [ADR-0062-ASSUMPTIONS] Assumptions and Applicability

- 当前宿主是单台 Windows，安装/修复/升级/卸载都需要管理员权限；普通运行时仍由独立虚拟服务账户执行。
- PostgreSQL 与 backend 是两个 SCM 服务，安装器不是长期 runtime guardian。
- 程序目录与数据目录跨文件系统/SCM/registry，无法获得一个数据库式原子事务，必须用 receipt + 补偿协议。
- 若未来采用版本化程序目录和原子指针切换，或支持 Linux package manager，本 ADR 的 Windows adapter
  实现需被新 deployment ADR refines/supersedes；领域和 PostgreSQL 合同不得依赖 Inno/SCM。

## [ADR-0062-DRIVERS] Decision Drivers

- 数据正确性优先：升级前必须先得到可识别的恢复点，失败不得继续覆盖。
- 任一重试必须知道上一次运行跨过了哪条破坏性边界，不能靠调用方布尔参数猜测。
- 安装、修复、升级、卸载和未来管理器 SCM 动作必须串行化。
- N-1 的服务配置只能用 N-1 规则解释；新文件落盘后才可用目标 N 规则验收。
- 外部同名服务、端口占用、argv 漂移、重解析点和 ACL 漂移一律 fail closed。
- “恢复点”“故障隔离”“自动回滚”必须是三个不同术语。

## [ADR-0062-ALTERNATIVES] Alternatives

### [ADR-0062-ALT-A] A. 每个脚本独立 best-effort 清理

代码最少，但崩溃后无法区分“尚未停服务”“已备份”“文件可能已覆盖”，调用方也能伪造
“备份已完成”。拒绝。

### [ADR-0062-ALT-B] B. 机器锁 + 持久回执 + 复制边界 + repair 恢复

选定。把可重试事实写入 SYSTEM-owned 回执；复制前尽量恢复原运行态，复制后只做故障隔离并要求
repair，绝不伪称已自动回滚。

### [ADR-0062-ALT-C] C. 版本化程序目录 + 原子指针切换 + 自动数据库 restore

目标更强，但当前没有对应实现、故障注入和 schema 兼容证明。作为后续切片，不阻断 B 成为当前
权威协议。

## [ADR-0062-DECISION] Decision

### [ADR-0062-C01] 发布策略与持久身份

`backend/packaging/windows-release-config.json` 是安装器服务名、端口、数据库名/角色、版本范围、
密钥强度和所有等待预算的单一真源。`pg_service_name`、`backend_service_name`、`db_name`、`db_role`
属于**持久身份**，不是普通调优参数；发生变化必须有显式迁移，不得由覆盖安装静默改名。

目标契约是：预检读取已安装 N-1 config，并按 N-1 的服务 argv、路径和身份解释旧安装；新服务
注册完成后才按目标 N config 验证。不能拿目标版本的默认值反推旧安装。

installer overlay 仍有一个明确例外：`InstalledReleaseConfigPath` 缺失时，preflight 会 clone 目标 N config
作为旧配置。它只可视为**待收口的 legacy adoption fallback**，不是 N-1 identity 已证明。正式发布前
必须二选一：缺失即 fail closed；或用独立 legacy registry/服务 argv/DB identity 证据明确认领，并把
认领结果持久化。当前不能宣称“所有旧安装都从 N-1 config 解释”。

### [ADR-0062-C02] 一台机器只有一个安装生命周期写者

安装、升级、修复和卸载共享位于 OS `CommonProgramFiles` 下的机器级零共享文件锁。锁目录与 owner
记录必须是 SYSTEM-owned、精确 ACL；子 PowerShell 只有在 64 位宿主、直接父进程、owner PID 和
仍被占用的锁全部一致时，才能复用 Inno 已持有的锁。

未来主机管理器的 UAC helper 也必须先取得同一把锁，并在锁忙时做到**零 SCM mutation**。当前
`desktop/backend_manager` 尚未接入该锁，因此“管理器与安装器可安全并发”仍是未完成项。

### [ADR-0062-C03] 安装模式必须由持久事实分类

只接受以下四种模式：

| Mode | 事实 |
| --- | --- |
| `fresh_install` | 无服务、无 PG 数据、无 env、无 PG bootstrap 恢复材料 |
| `preserved_data_reinstall` | 数据与 env 完整，但两服务均不存在 |
| `repair_install` | 有可验证数据，但服务状态不完整 |
| `upgrade` | 两服务、PG 数据和 env 均可按旧契约证明 |

“部分存在但无恢复材料”的混合态不是第五种模式，必须拒绝覆盖。

### [ADR-0062-C04] 生命周期回执是状态机，不是日志

回执固定写在受保护机器锁目录，owner 为 SYSTEM，访问只给 SYSTEM/Administrators，并绑定本轮
install root、data root、端口、旧服务状态/启动策略、N-1 config、备份要求与路径、owner PID。
合法单向状态为：

```text
captured
  -> prepared
  -> files_may_have_been_replaced
  -> install_completed
```

- `captured`：本轮输入和旧服务状态已捕获；不得提前声称备份完成。
- `prepared` 的**目标语义**：若检测到既有 PG data + env，需要的 `pg_dump -Fc` 已生成并通过
  `pg_restore --list` 可读性检查，旧服务已进入安全复制态；只有此状态允许 Inno 开始覆盖。
- `files_may_have_been_replaced`：跨过复制边界。该名称故意保守——不要求证明每个文件真的被写过；
  一旦可能覆盖，就不能再按 pre-copy 路径恢复旧运行态。
- `install_completed`：服务注册、数据库/后端启动与 bootstrap 后置步骤成功。它应当只在 Inno 的
  安装元数据也持久化后成为最终 commit point。

禁止跳级、倒退、复用已完成回执，禁止由调用方传入“备份已完成”绕过回执。

installer overlay 已把 `preserved_data_reinstall` 与 PG 服务缺失的 `repair_install` 收紧为：先验证/保存
受保护的 PG recovery toolset，临时注册 recovery PG 服务，完成 dump 和 archive list validation，再允许
`captured -> prepared`。这修掉了旧的 post-copy 补备份路径，但**没有闭合复制边界本身**：

- `PrepareToInstall` 结束时持久回执仍为 `prepared`；
- Inno 到 `CurStepChanged(ssInstall)` 只把 `LifecycleFilesMayBeReplaced` 设为进程内布尔值；
- 真正的 `prepared -> files_may_have_been_replaced` 持久写入要等 `[Files]` 已运行、
  `ssPostInstall` 调用 `install_bundled_services.ps1` 后才发生。

因此 hard-kill、断电或 Inno 进程损坏可以发生在“程序文件已部分覆盖、磁盘回执仍写着 `prepared`”的
窗口。下一次 installer 当前会保守地把 stale `prepared` 当作已覆盖来隔离，这降低了误启动概率，
但不能把当时的 durable state 叫作已跨过复制边界，也不能证明其他恢复入口不会按旧状态解释它。
这是 Release Blocker，而不是文字勘误。

### [ADR-0062-C05] Pre-copy 恢复与 post-copy 故障隔离不同

升级的真实执行者是 Inno `PrepareToInstall` 调用 `prepare_bundled_upgrade.ps1`，不是主机管理器或
`backup_service.create_manual_backup()`。它用**旧版本捆绑 PG 工具**验证旧服务账户、完整 argv、
loopback `DATABASE_URL`、数据库/角色/端口与 data directory，再执行：

```text
capture -> stop backend -> pg_dump -Fc -> pg_restore --list -> stop PG -> prepared
```

在 `prepared` 之前失败，可以按回执恢复旧服务启动策略与运行态。进入
`files_may_have_been_replaced` 后失败，只能停用/停止不可信服务、写
`installer-recovery-required.json`，并要求重新运行 installer repair。

恢复标记本身也是承重状态，不能按普通日志写入。installer overlay 的
`Write-TicketboxInstallerRecoveryMarker` 目前直接 `WriteAllText(target)`，随后才设置 ACL；没有同目录临时
文件、内容/文件 durable flush、原子 replace 和 replace 后复读。断电可能留下不存在、截断或权限窗口内
可见的 marker。正式实现必须先在受保护目录创建精确 ACL 的临时文件，写入并 durable flush，原子发布，
再复读校验；任一步不能证明成功时，两服务继续保持 disabled/stopped，repair 不能以 marker 缺失推断安全。

对 `preserved_data_reinstall` / PG-service-missing repair，目标同样是**复制前**使用已保存并重新验证的
PG recovery toolset 取得 restore point；installer overlay 已实现该方向。工具 provenance、data
directory、DB/role/port、backup path 与 receipt 必须一致，且 recovery service 必须在进入
`prepared` 前移除。该进展不抵消 C04 的 durable copy-boundary 缺口。

### [ADR-0062-C06] 恢复点不等于自动回滚

当前 `pg_dump -Fc` 只是**数据库 restore point**：

- `pg_restore --list` 只证明 archive 可解析，不证明能在隔离数据库完整 restore；
- 回执当前绑定路径与 ACL，但未绑定 archive 的 SHA-256、大小和生成 PG 身份；
- dump 不包含程序二进制、Windows 服务配置、PG global roles 或完整运行配置；
- 当前没有自动 restore、版本化程序目录、schema 前后兼容证明或故障注入演练。

因此文档只能说“复制前存在经结构校验的恢复点”和“复制后 fail closed”，不能说“升级可自动回退”。
要升级为自动回滚，必须另片完成独立 SYSTEM/Admin-only rollback archive、内容指纹、隔离 restore +
invariant smoke、二进制切换和 failure injection。

### [ADR-0062-C07] 启动验收不是持续 readiness

当前后端启动前会等待 DB 并执行初始化；安装器还证明
`SCM service -> Shawl process -> backend listener process` 的 PID/路径链，再请求固定 loopback
`/api/health`。这构成**本轮 startup acceptance gate**。

`/api/health` 本身仍只返回 `{"status":"ok"}`，不能证明运行期间 DB 一直可服务，也不能证明
backend build fingerprint、Alembic head 或 data directory 与本轮 manifest 一致。上述 attestation
仍是未完成项，不得称为“真实持续 readiness”。

### [ADR-0062-C08] ACL、路径和卸载边界

- 数据根断继承；SYSTEM/Administrators 对全树继承式 FullControl。
- PG/后端虚拟服务账户在根仅有非继承 ReadExecute，分别只对 `pgdata/`、`app/` 子树拥有
  FullControl，避免父目录 `DELETE_CHILD` 形成跨树删除权。
- 宽泛 `Users` 不得读取数据根；legacy 后代需重置 owner 和精确 ACL。
- 路径必须是固定本地盘、位于允许域、无重解析点；卸载删数据还需 registry、安装标记、服务/进程/
  端口与目录身份同时一致。
- 普通 Inno 卸载器当前**总是保留数据**。`-DeleteData` 只是管理员手工脚本能力；“卸载器复选框 +
  二次确认”仍未实现。

自选 data root 的祖先 reparse 检查当前不是从卷根逐级持 handle 的原子证明；对低权限可写父目录的
junction-swap/rename TOCTOU 仍需故障注入或改为拒绝此类祖先。

## [ADR-0062-CALIBRATION] Current Implementation Calibration (dual baseline, 2026-07-11)

`implementation_status=nonconformant`、`verification_status=failed` 以可发布主线和本次故障边界审查为准。
右列只是未提交候选实现进展；它不能成为“主线已实现”的证据。

| Capability | `main@0f1092e625` | uncommitted installer overlay / audit result |
| --- | --- | --- |
| release config + 持久身份兼容门 | not implemented | implemented / partial；缺失 installed config 时仍有 legacy adoption fallback |
| SCM 注册、dependency、delayed-auto、failure actions | best-effort script | implemented / partial；写入已检查，完整 read-back 漂移证明仍不全 |
| 机器级锁 + parent/owner proof | not implemented | implemented for installer/manager candidates；尚无已合并、实机跨进程证据 |
| 四模式分类 | not implemented | implemented and contract-tested locally |
| `captured -> prepared` 回执 + pre-copy dump | not implemented | upgrade/preserved/repair 均已有 overlay 路径；fresh 无需 dump |
| durable copy-boundary transition | not implemented | **failed / Release Blocker**；`ssInstall` 只写 Inno 内存布尔值，持久 transition 晚于 `[Files]` |
| post-copy fail-closed + recovery marker | not implemented | behavior present；marker 直接写 target 后设 ACL，不是 durable atomic publish |
| exact ACL / owner / reparse / uninstall guards | not implemented | implemented / partial；祖先 TOCTOU 和真实 hostile-path 演练未完成 |
| startup listener/process identity + minimal health | not implemented | implemented / partial；无持续 readiness 与完整 build/DB/schema attestation |
| final commit point | not implemented | partial；receipt 的 `install_completed` 仍早于 Inno 最终安装元数据持久化 |
| clean no-Python install/upgrade/repair/uninstall E2E | not implemented | not verified；没有 clean VM / power-loss evidence |

## [ADR-0062-CONSEQUENCES] Consequences

Good：重试不再靠猜；已持久化的旧/新配置解释边界明确；复制前可补偿、复制后保守隔离；“恢复点”
和“回滚”不再混用。Bad：回执和锁成为高承重协议；任何新增管理器/修复工具都必须复用它们；缺
N-1 config 的 legacy adoption、durable copy boundary、原子 recovery marker 和最终 commit point 尚未
闭合，post-copy 失败仍需要人工 repair。overlay 修掉 preserved/repair 的复制后备份，不代表这些
Release Blocker 已消失。

本 ADR 不 supersede [[0047]] 的分发形态，只替代其零散的安装生命周期实施描述。

## [ADR-0062-REVERSIBILITY] Reversibility, Replacement and Retirement

机器锁、receipt 和 copy-boundary 可被版本化目录/原子切换实现替代，但在新实现完成故障注入前不得删除。
PG 数据一旦由新 schema 写入，二进制回滚可能基本不可逆；此时只允许前滚修复或经验证的数据 restore，
不能只恢复旧 EXE。退役旧 receipt schema 时必须支持未完成 N-1 receipt 的识别/隔离，不能当 fresh install。

复审触发：安装规模超出单机、需要无人值守批量部署、Windows adapter 之外新增宿主、pre-copy 保护无法在
目标时限内完成、或 post-copy repair 的实测失败率不可接受。

## [ADR-0062-EVIDENCE] Verification and Evidence

以下三项是 Release Blocker：durable copy-boundary transition、durable atomic recovery marker、
receipt 与 Inno 最终安装元数据的一致 commit。它们必须用真正终止进程/断电等价故障验证，不能只用
mock 返回码或脚本文本匹配代替。

- 模式分类、非法混合态、回执跳级/复用/输入错绑均有 contract test。
- 删除 installed release config、同时把旧服务/DB identity 改成非目标值：preflight 必须 fail closed，
  不能按目标默认值把它分类成 preserved/repair。
- 给定 PG data + env 且 PG 服务缺失：在 Inno 首次覆盖前必须已有本轮受保护 restore point；在
  pre-copy 与 service-layer backup 之间注入断电不得留下“已覆盖但无 dump”状态。
- pre-copy 任一步失败时，未覆盖文件且原服务态可恢复。
- post-copy 模拟失败时，两服务不能以不可信新旧混合态继续运行，并留下 repair marker。
- 在 `CurStepChanged(ssInstall)` 后、首个 `[Files]` 覆盖前/中/后分别 hard-kill Inno：磁盘必须在任何
  可能覆盖前已经持久表达 `files_may_have_been_replaced`；不能依赖 `DeinitializeSetup` 或进程内布尔值。
- 在 recovery marker 写入内容、flush、发布和 ACL 校验各点注入 kill/power-loss：下一次 repair 必须把
  缺失/截断/临时文件/ACL 漂移全部判为不安全状态，并保持服务隔离。
- 机器锁被占用时，安装/修复/卸载均零 mutation；管理器接线后同样验证 start/stop/restart。
- 真实 upgrade 在 disposable 数据库执行 dump -> restore -> identity/schema smoke 后，才允许把“可恢复”
  写进发布说明。
- 最终 commit point 测试覆盖 receipt 与 Inno registry 写入之间的失败窗口。

反向验收：任一既有数据模式能在 `backup_required=true/backup_completed=false` 时跨过 copy boundary；
文件可能已覆盖而 durable receipt 仍是 `prepared`；marker 在断电后消失/截断却被当成安全；或
receipt/registry 分裂后仍报告成功，任一发生即证明本契约尚未成立。当前 overlay 已命中第二项，故
verification 是 `failed`。

## [ADR-0062-REFERENCES] References

- Microsoft `sc.exe config` 官方契约支持 `depend=` 与 `delayed-auto`：
  <https://learn.microsoft.com/windows-server/administration/windows-commands/sc-config>
- PostgreSQL 17 `pg_ctl register` 是 Windows system service 注册入口：
  <https://www.postgresql.org/docs/17/app-pg-ctl.html>
- PostgreSQL `pg_dump`/`pg_restore` 的 archive 能力：
  <https://www.postgresql.org/docs/17/app-pgdump.html>
