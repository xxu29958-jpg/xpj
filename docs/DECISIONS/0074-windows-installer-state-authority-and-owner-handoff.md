+++
schema_version = 2
id = "0074"
title = "Windows 安装器状态权限域与 owner handoff 原子交接"
summary = "分置 installer 权威与 backend-readable 运行投影，以不可变进程身份、原子状态机和显式租约交接完成可重入安装事务"
current_scope = "Windows 正式安装、修复、升级中的 lifecycle identity、owner handoff、installer recovery latch、runtime guard、委托操作租约、legacy 状态迁移、发布审计基线与未来宿主拓扑扩展边界"
date = "2026-07-12"
decision_status = "accepted"
implementation_status = "partial"
verification_status = "unverified"
decision_type = "deployment-runtime"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "Windows installer adapter 维护者"
verification_owner = "独立安装/恢复 reviewer + clean-machine CI"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "amends"
target = "0062"
scope = "installer recovery latch 的机器权限域、原子发布、迁移与前滚 repair"

[[relations]]
kind = "amends"
target = "0063"
scope = "owner handoff 父目录权限、pending/confirmed 原子转换、完成页清理与中断接管"

[[relations]]
kind = "depends-on"
target = "0065"
scope = "accepted 历史不改写，以后继 ADR 修订当前 Windows adapter 裁决"

[[relations]]
kind = "refines"
target = "0066"
scope = "安装器、SCM、Inno 与 PowerShell 保持平台适配层，不进入家庭财务核心"

[[relations]]
kind = "informational"
target = "0006"
scope = "PS5.1/PS7 只是同一 Windows 脚本合同的兼容宿主"
+++
# 0074 Windows 安装器状态权限域与 owner handoff 原子交接

## [ADR-0074-SCOPE] Context, Scope and Non-goals

main@83af67d0 最先暴露的是两个 owner handoff 发布阻断：已有 pending 无法进入 confirmed，以及 handoff/latch
寄生在 backend 对父目录拥有 FullControl 的 DataRoot\app。沿安装、holder、handoff、卸载和发布 gate 的完整调用链继续追踪后，
它们与复审发现的边界问题收束为三条根因合同，而不是一组互不相关的字面修补：

1. **生命周期身份与租约连续性。** PID 不是不可变身份；holder ready、owner record 和 handoff 若在不同时间重新按 PID
   解释进程，PID 重用会把权威绑到无关进程。DataRoot 启动方若在 holder 获得目录句柄、发布 marker/ready 前释放 operation
   lease，则 owner 崩溃窗口内还会失去从机器锁到目录 lease 的连续屏障。
2. **机器状态必须严格分类。** Windows 路径命名空间大小写不敏感，file-shaped root、directory-shaped guard、reparse、
   malformed receipt/staging 都不能借 `Test-Path -PathType` 或大小写敏感枚举伪装成“不存在”。
3. **验证基线本身是权威输入。** 显式 exact ref 或 CI 上下文若无法读取比较基线，release audit 必须失败；只在 PR 上
   fail closed 会让 push/manual lane 跳过 ratchet 并产生假 PASS。

因此本切片同时修正权限拓扑、原子状态机、不可变进程身份、显式租约交接、严格状态分类与审计基线选择。只修任何一个
表面症状都会留下同一根因链上的未封闭窗口。

本 ADR 不宣称已实现自动数据库 restore、N-1 二进制降级、sealed recovery principal、多安装实例、Linux
部署、云端密钥管理或 IPv6。它为这些后续拓扑留下明确边界和复审触发，但不把目标写成当前事实。

## [ADR-0074-ASSUMPTIONS] Assumptions and Applicability

- v1 正式分发是单台 64 位 Windows 上的一套安装：固定 AppId、HKLM 产品登记、两项 SCM 服务和一把机器锁。
- PostgreSQL 是数据库权威；DataRoot 是可保留、备份、恢复或迁移的业务数据域，不是安装事务权威。
- 安装、修复、升级、卸载和提权 helper 都必须持同一机器生命周期锁。
- PS5.1 与 PS7 是同一脚本的兼容执行宿主，不是两套配置、业务或生命周期引擎。
- GUI 是状态投影和命令入口；关闭 GUI 不终止服务，GUI 不直接操作数据库，也不成为配置真源。

## [ADR-0074-DRIVERS] Decision Drivers

- backend/PG 账户不能读、写、删除、改名或替换承重安装状态，其父目录也不能给它们删除子项的权利。
- repair latch 不得随 DataRoot 备份或恢复倒退；未完成 handoff 不得随业务数据克隆到另一台机器。
- 首次发布、受控替换、崩溃重试和 legacy 迁移必须有不同且可审计的语义。
- 路径从 OS 特殊目录和已持有锁动态派生，不写死盘符、用户目录、PowerShell 安装位置或端口。
- 当前单安装边界必须诚实；不能只加一个 GUID 目录就冒充多实例已经成立。

## [ADR-0074-ALTERNATIVES] Alternatives

- **A. 继续放在 DataRoot\app，只收紧子文件 ACL。** 拒绝；backend 对父目录的 DELETE_CHILD
  不会被子文件 ACL 收回。
- **B. 放在 DataRoot\installer-state。** 比 A 安全，但仍拒绝；它能隔离 backend/PG，却把机器安装
  事务绑到可保留、可恢复、可克隆的数据卷。旧 DataRoot 快照可能让 repair latch 倒退，未完成 handoff
  也可能被复制到另一台机器。
- **C. 立即建立 installations\<guid> 并把 lock、receipt、identity、tools 全部迁入。** 长期方向可行，
  本次拒绝；当前 AppId、HKLM、服务名、端口和机器锁仍是单例，只把目录命名空间化会伪装成多安装支持，
  并扩大首个安全修复的迁移面。
- **D. 在现有机器生命周期根下建立独立 installer-state。** 选定；它复用已受保护的机器根和全局锁，
  关闭 DataRoot 回滚/克隆耦合，同时不虚构多实例能力。

## [ADR-0074-DECISION] Decision

### [ADR-0074-C01] 状态按权威和权限域分置

| 权限域 | 内容 | 允许写入者 | 恢复语义 |
| --- | --- | --- | --- |
| OS CommonProgramFiles\Ticketbox 机器生命周期根 | global lock/owner、operation lock、完整 lifecycle receipt、受保护 recovery intent/tools | SYSTEM/Administrators；持锁 installer/helper | 机器安装事务权威，不随 DataRoot restore 回滚 |
| 机器根下 installer-state | owner-bootstrap.txt、owner-handoff-pending、installer-recovery-required.json、delete-data-in-progress.json | SYSTEM/Administrators；持锁 installer/完成页 helper | 短命交接、单调 repair latch 与绑定删除续跑意图；不是完整 lifecycle receipt |
| OS CommonApplicationData\TicketboxRuntimeState | 无 secret 的 backend-readable `installer-runtime-recovery-pending` | SYSTEM/Administrators FullControl；backend 服务账户 ReadExecute | 独立运行阻断投影，不随 DataRoot restore 回滚；不能授权 commit/repair |
| OS CommonApplicationData\TicketboxRuntimeBinding | `data-root` junction，目标是 v2 marker 声明卷上的 DataRoot Volume GUID 路径 | SYSTEM/Administrators 创建/替换；PG/backend 服务账户只继承 ReadExecute | SCM 的稳定卷绑定路径；不是配置真源，也不能替代 marker/receipt |
| DataRoot 根 | data-root marker、installation identity witness、installer backup | installer 写；服务只获得明确最小读取权 | 数据绑定与候选恢复材料，可被备份但不能替代机器事务 |
| DataRoot\app / pgdata | runtime config、uploads/logs、PostgreSQL 数据 | 对应 backend/PG 服务账户与管理员 | 业务/runtime 数据；不得承载 installer handoff 或 receipt 权威 |

installer-state 关闭继承，仅允许 SYSTEM/Administrators。目录已存在时必须先验证 owner、继承和精确 ACL；
目录本身及所有祖先不得是 reparse/junction。不允许先递归“修好”异常目录再把原状态当可信；机器生命周期根
同样如此，历史 ACL 漂移必须中止并交给独立 repair，不能在同次运行修复后继续相信 handoff/latch 缺失。
首次创建机器根或 installer-state 时，PS5.1 通过 `DirectoryInfo.Create(DirectorySecurity)`、PS7 通过等价 ACL
extension，让目录从命名空间可见的第一刻就具有最终 owner/ACL，不保留“先 New-Item、后收紧”的断电窗口。
machine runtime-state 目录同样从 OS special folder 动态解析、拒绝与 DataRoot 包含或重叠，并以最终 ACL 原子创建；
backend 的 ReadExecute 只用于读取运行阻断投影，不包含写、删除、改名或替换权。
所有消费者必须按同一 no-follow 语义区分 absent、普通目录根 + 普通文件 guard、file-shaped root、directory-shaped guard、
reparse 与其他 malformed 形态。PowerShell 以 `FILE_FLAG_OPEN_REPARSE_POINT` 打开并分类每级 entry；frozen launcher
不调用 `resolve()`，而是对 lexical 祖先链逐级 `lstat()`。dangling junction/symlink、file-shaped 祖先、不可读取 entry、
类型错位或任何 reparse 都是 malformed，不能被 `Test-Path -PathType` 或跟随链接后的“不存在”冒充 absent。
DataRoot 目录链 holder 在逐级 no-follow 句柄保护下，以最终 SYSTEM/Administrators ACL 原子创建缺失节点。缺失根的
provisioning 先在机器生命周期根持久化绑定 DataRoot/InstallDir 与 Windows Volume GUID 的 intent：现存祖先必须已经逐级验证并持有禁止 delete/rename
的句柄，intent 又必须在第一个缺失节点可见前写入并复读。这样 file/reparse 祖先在 intent 发布前就会拒绝，而目录创建或
marker 发布中断后，下一次相同绑定可以识别自己的半成品。恢复只允许精确 ACL 的空根，并且只清理严格命名的
`.ticketbox-protected-<guid>.tmp` / `.ticketbox-durable-<guid>.tmp` staging；marker 写入、复读和绑定校验完成后才退役 intent。
marker 自身从临时文件创建时起就必须关闭继承、由 SYSTEM 拥有且只允许 SYSTEM/Administrators FullControl；fresh gate
同时验证根目录精确 ACL、marker 的 no-follow 普通文件形态、精确 ACL/owner 和 JSON 绑定，不能把路径相同的伪 marker 当权威。
当前 `ticketbox-data-root-v2` marker 必须同时绑定规范化 DataRoot、InstallDir 与 Windows Volume GUID；路径相同但卷身份不同的
marker 不能授权 fresh、恢复、运行时 guard 或删除。provisioning intent 只有在受保护 v2 marker 复读成功且 marker 内卷身份与当前挂载卷
一致后才可退役，因此盘符/VHD 的 ABA 切换至多留下需要显式 repair 的失败状态，不能把另一卷上的 marker 变成权威。
Volume GUID 只能在目标路径现存祖先已验证并持句柄后的首个创建回调中采样；根句柄取得后、marker 发布后又分别复核，
任一阶段盘符换卷都保留 intent 并 fail closed。中断 intent 固定原 DataRoot/InstallDir/Volume GUID，只允许同路径同卷重试；
改选路径必须进入未来显式 recovery 协议，不能靠两次路径查询“证明 absence”后自动 replace intent，否则热插拔/VHD 换卷仍会
制造两个候选权威根。

正式 SCM 不继续使用可被另一卷复用的盘符 DataRoot，也不把 PostgreSQL 不可消费的裸 Volume GUID 路径硬塞给 `pg_ctl`。
安装器从 OS `CommonApplicationData` 动态派生专用 `TicketboxRuntimeBinding` 根，以最终 protected ACL 原子创建，并只给两项
虚拟服务 SID 可继承的 ReadExecute；其唯一子项 `data-root` 是指向
`\\?\Volume{guid}\<DataRoot-relative-path>` 的 junction。读取者必须同时复核 binding 根无 reparse 祖先、精确 ACL、子项确为
唯一 junction、目标等于 v2 marker 推导值且当前可达。PG 的 `-D`、Shawl cwd/log 与 `TICKETBOX_DATA_DIR` 只使用这个稳定普通路径。
因此原卷离线、VHD/盘符被另一卷接管时，服务不会静默落到同名 replacement tree；junction 继续绑定原 Volume GUID 并失败关闭。

runtime binding 不是第二配置引擎。DataRoot/InstallDir/卷身份仍由 v2 marker、机器 receipt 和安装输入共同裁决；junction 只是
Windows 宿主适配。frozen launcher 要求 SCM 同时注入两类 recovery guard 路径、marker 路径与 Volume GUID，四项必须完整出现；它在创建 `uploads`、读取
`.env` 或导入应用前拒绝 reparse marker，复读严格 v2 JSON，校验 marker DataRoot 等于稳定 junction 的最终目标、InstallDir 等于
当前 frozen executable 根，并用 `GetFinalPathNameByHandleW(VOLUME_NAME_GUID)` 证明 junction 最终卷与 SCM/marker 一致。
`.env` 加载后再次恢复四项宿主权威，backend 可写配置不能移除或改绑它们。只有非 frozen 源码开发模式可以不带该宿主合同。
若本次创建 DataRoot，必须在发布 ready 前写入并复读绑定 InstallDir 的 data-root marker；若 DataRoot 预先存在、为空且没有
marker，必须在 ready 前拒绝，因为低权限进程可能仍持有目录收编前取得的可写句柄。非空无 marker 布局不能在 holder 或后续
repair/preserved-data 中按目录形状猜测；所有普通安装路径都在任何 recovery-service/ACL mutation 前拒绝，只有受保护 v1 marker
可进入原子 v2 迁移。禁止先以继承 ACL 创建目录、再依赖事后递归 ACL reset 获得可信根。
Inno 不创建、覆盖或硬化机器根、lock、owner。它先读取自身 Windows process creation FILETIME，再解出专职 PowerShell
lifecycle-lock holder；holder 必须打开 owner 的 `SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION` handle，从该 handle
读取 creation FILETIME 并验证它是直接父进程，之后在 holder 整个生命周期只等待这一个 handle，不再按 PID 重新打开进程。
验证完成后才对既有根取得 no-follow 目录链 lease 并验证 owner/继承/精确 ACL，或用最终 security descriptor 原子创建新根。机器 owner record 使用
`ticketbox-lifecycle-owner-v2`，同时持久化 PID 与 creation FILETIME high/low；后续 child authorization 和 owner handoff
只消费这份已验证的不可变身份，不按 PID 重新解释当前进程。

holder 随后以最终 ACL 创建并持续持有 lock、原子发布 owner。ready/release IPC 只能位于已验证的机器根，使用相同精确 ACL。
holder 完成机器根验证并拒绝 stale IPC 后，先向独立受保护 transient bootstrap 写入绑定当前 owner 身份的精确
`root_validated` 短命握手；Inno 在接受该握手前不得探测机器根子项。该握手不持久化、不授权 mutation，也不是第二真源。
holder 生成 256-bit 随机 nonce，并在 ready 中同时声明 holder PID、holder creation FILETIME 与 PowerShell provider 解析出的
installer-state 绝对路径。Inno 只接受与当前 owner/nonce 完整匹配的 ready，再用 `OpenProcess` + `GetProcessTimes` 取得
PID 与 creation FILETIME 同时匹配的同步句柄并持续持有；PID 已复用即拒绝，不能把 Exec 的 ResultCode 或 PID 文本当作子进程身份。
原子 release 必须回传 nonce。installer-state 路径只验证其仍在机器根直属域并消费 provider 值，不再由 Pascal 复制目录名。

Setup 阶段所需的 holder、安装/升级脚本、release config 与 provenance verifier 不从宽权限 `{tmp}` 直接提权执行。
Inno 每次运行都在 OS CommonProgramFiles 下创建独立的受保护 transient bootstrap 目录，把内嵌文件复制进去、施加
SYSTEM/Administrators 精确 ACL，并逐个核对构建时注入的 SHA-256 后才调用；复制边界前再次全量复核。该目录不存放
lock、receipt、handoff 或其他权威状态，清理失败只留下可验证的发布输入，不会形成第二真源。运行期生成的 transcript
runner 也只能写入该受保护目录，施加精确 ACL 后记录 SHA-256，并在每次 PowerShell 宿主调用前复核；不得从 `{tmp}`
执行动态生成的提权脚本。每个 mutation child 必须先独占 operation lock，再验证它仍是记录中 Inno owner 身份对应进程的
直接子进程且主锁仍被 holder 持有；operation lock 是该次调用的委托租约，不是第二把安装权威。机器 holder 收到正常 release
或观察 owner 死亡后，只在没有活动 operation lease 时释放主锁；有活动 lease 时保留主锁直到 child 返回。

DataRoot 长命 holder 只能由专用 `hold_data_root_mutation_guard.ps1` 承担；它不加载 release config、服务、数据库或
receipt 逻辑，`prepare_bundled_upgrade.ps1` 只负责短命升级准备。holder 启动后先以当前 installer owner 取得委托
operation lease，再取得 no-follow 目录句柄、创建/验证 marker、原子写入并复读绑定 holder PID + creation FILETIME + nonce
的 ready，最后才通过显式 `OnLeaseReady` 回调释放启动 lease。任何一步失败都在同一脚本的 `finally` 中回收 lease，
不能在进入长等待前提前释放。交接完成后，holder 采用与机器 holder 相同的 owner-death 规则：只等待首次验证的
owner handle；该 handle signaled 或收到正常 release 后，若另有委托调用持有 operation lock，则继续保留目录句柄，待其释放后
才清理 ready/release/tmp IPC。这样从机器锁、启动租约、目录句柄到长命 holder 的权威屏障没有空窗，orphan child
也不能在屏障消失后继续 mutation。

operation lock 自身也必须按 no-follow 形态分类并以最终 ACL 受保护打开；reparse、目录、不可读、分类期间的 sharing violation
或其他 malformed/不可判定状态一律视为“仍有活动或状态不可判定”，holder 不得因此释放机器/DataRoot 权威。若专用
holder 在 ready 前退出而无法写回 acknowledgement，Setup 只能同步调用同一专用脚本的 `-ConfirmStopped`；该路径先取得 operation lock，
再证明 ready 不存在且 abort 精确绑定当前 owner。若 ready 已发布后 holder 死亡，确认路径还必须匹配 Setup 已验证的 holder
PID + creation FILETIME + nonce，证明原 holder 身份已不存活，才能清理 IPC。无论 holder 自行退出还是同步确认，都只有在
DataRoot guard 和 operation lease 均已释放后，才可用同一个已验证 owner handle 确认 Setup 仍存活，再以原子 replace + write-through
将 control artifact 收敛为 `stopped` 并复读。Setup 在收到 acknowledgement 或完成上述同步不活证明前，不得清空本地 holder 状态或同进程重试。

公开 `Global` mutex 与 Inno `AppMutex` 可被低权限进程预先占用，不能成为提权安装器的可用性或安全前置条件，因而不进入本合同。
PowerShell holder、受保护机器锁、owner record 和 receipt 是 setup/uninstall/GUI 跨入口唯一串行生命周期权威。Inno 在每个复制、服务安装和 commit 边界复核 holder 进程仍存活；
ACL 漂移、junction 或 holder 失败时不会先触碰机器根子路径。PowerShell
从 OS CommonProgramFiles 动态解析权威路径，Inno 只传入独立解析结果做一致性校验，不写死 C:\...。

### [ADR-0074-C02] Owner handoff 是独立可重入状态机

    absent
      -> pending (CreateNew only)
      -> confirmed (validated atomic replace)
      -> cleaned (credential first, marker last)

- 首次 pending 必须 CreateNew；目标已存在即拒绝覆盖。
- pending -> confirmed 与死亡安装器 rebind 只有在 installation binding、generation、credential hash、
  owner PID/creation FILETIME、进程存活状态和 ACL 全部校验后，才允许显式原子替换。
- handoff writer 必须消费进入机器生命周期锁时已验证并冻结的 owner identity；禁止在写 marker 时再次只按 PID 查询
  `Get-Process.StartTime`。这样 installer 在授权 child 后退出、PID 又被复用时，marker 仍绑定原 lifecycle owner，不会把无关进程晋升。
- 接管发生在当前 installer 已独占机器生命周期锁的前提下；只有目标 PID 的当前进程 creation FILETIME 与 marker 精确相等的
  正向证据才把旧 owner 判为存活。PID 已复用、进程不存在或 creation time 无法读取都不能无限保留旧 owner authority。
- 替换使用同目录、预先施加精确 ACL 的临时文件，flush 后执行
  MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH，再复读内容、owner 与 ACL。
- 临时文件在进入 MoveFileEx 前必须已经具备最终 owner、精确 ACL 和严格 UTF-8 内容；不能先发布一个
  当前管理员所有的权威路径，再依赖发布后的补写修正权限。
- durable confirmed 先于敏感 credential 删除；marker 最后删除。confirmed + credential、
  confirmed only 与全空重试必须确定性收敛，不得再次展示或复活凭据。
- HTTP bootstrap 已提交并写出 pending+credential、但 `.env` 尚未退役 secret 时，repair 只验证现有
  handoff、移除 secret、重启并复核 health；不得再次调用 bootstrap HTTP 或新建 generation。
- SHA-256 只绑定内容完整性，不承担口令抗穷举；抗猜依赖高熵 secret/HMAC 与机器 ACL。

### [ADR-0074-C03] Legacy 迁移必须停服、持锁并可重入

旧 `ticketbox-data-root-v1` marker 只有路径绑定，没有卷身份，不能授权 fresh、删除或正常运行时动作。DataRoot holder 只可借它
维持 no-follow 目录 lease；repair/upgrade/preserved-data 必须先用既有安装证据确认 v1 的路径绑定。证明完成后、任何 recovery-service
或 ACL mutation 前，安装器以同目录受保护临时文件和 `REPLACE_EXISTING | WRITE_THROUGH` 把 v1 收敛为
`ticketbox-data-root-v2`，复读精确 ACL、路径和当前 Volume GUID。证明失败时保留原状态并 fail closed，不能为了升级 schema 覆盖 marker。
完全缺少 marker 的非空树无法证明其 PostgreSQL 内容未被低权限主体改写，普通 installer 一律拒绝；恢复必须在未来独立隔离环境中完成逻辑导入，不能先补文件 ACL 再把历史内容当可信。

data-root v2 权威成立、backend 已停止且机器 operation lock 仍持有后，legacy installer-state artifact 按以下顺序收敛：

1. 先迁移 app\installer-recovery-required.json，避免后续 owner 冲突进入补偿时改写双位置 latch；
2. 在移动任何 owner artifact 前，预检 legacy/current 两侧全部现存文件；
3. 成对迁移 app\owner-bootstrap.txt 与 app\owner-handoff-pending。

DataRoot 与 CommonProgramFiles 可以位于不同卷，因此不能把 `MoveFileEx` 或 `MOVEFILE_COPY_ALLOWED` 的
copy+delete 伪装成跨卷原子 rename。每个文件先验证 legacy owner/ACL/reparse 与 bounded strict UTF-8，随后在
current 所在卷创建已施加精确 ACL 的临时文件，flush 后以 CreateNew 原子发布，复读并逐字节确认，最后才删除
legacy。某一 artifact 已在 current、legacy 不存在时可继续；新旧同一 artifact 同时存在且逐字节相同，视为
“目标已发布、源尚未删除”的可恢复状态并只删除 legacy；内容不同则保留两者并 fail closed。目录、重解析点、
超限文件或无效 UTF-8 不能被当成“不存在”。崩溃后重试还必须能从“credential 已迁移、marker 未迁移”和相反
的历史分裂状态收敛。

旧布局可能只有 credential、没有 marker。该路径必须保留 legacy credential 作为迁移来源证明，先以 CreateNew
发布 current credential，再创建并复读绑定 installation/generation/hash/installer owner 的 pending marker，最后
删除 legacy 来源。若在 marker 发布前后崩溃，重试利用仍在的 legacy 来源继续；current 位置单独出现 credential 且
没有 legacy 来源或 marker 时必须 fail closed，不能把它命名为“legacy”后展示或删除。

受保护 writer 的 `.ticketbox-protected-<guid>.tmp` 与旧版 `.ticketbox-durable-<guid>.tmp` 是唯一可识别 staging
命名空间。持 operation lock 且父目录精确 ACL 已验证后，repair/uninstall 可收紧并删除这两类普通非 reparse
残留；零长度和写完待 rename 都能收敛。相似但不满足完整 GUID 格式的名称继续视为未知状态并 fail closed。

-CompleteOwnerHandoffOnly 只确认并清理 current 域，不在 backend 已运行时偷偷迁移 legacy 文件；
发现 legacy handoff 时要求重新运行 repair。

### [ADR-0074-C04] Recovery-required 是单调 latch，不是完整状态机

installer-recovery-required.json 只表达“程序文件可能已替换，服务必须保持隔离并运行 repair”。它绑定
InstallDir/DataRoot、schema 与原因，但不替代 lifecycle receipt 的 generation/stage。latch 缺失不能单独证明
安全；receipt、SCM、数据根和运行身份仍需共同校验。

当前 lifecycle receipt schema 为 `ticketbox-windows-lifecycle-receipt-v7`。创建 receipt 前必须复读受保护 v2 marker，并把
`data_volume_identity` 固化进机器 receipt；以后每次读取、owner rebind、stale recovery、commit 或卸载都先证明 receipt、marker
和当前挂载卷三者一致。marker 缺失、卷身份格式错误或路径相同但卷已替换时，在服务/ACL/backup mutation 前拒绝。

runtime binding 的服务迁移是受 receipt 约束的精确两态转换，不是宽松 argv 兼容：binding 未发布时只接受旧盘符直连合同；
junction 已发布而安装事务仍处于 post-copy repair 时，每项服务分别只可匹配“旧直连”或“新稳定别名”完整合同，允许一项已迁移、
另一项尚未迁移的硬终止断点；任意第三种 cwd、`-D`、env、dependency、account 或 payload 都拒绝。正式 commit、Desktop Manager
只读校验和正常运行只接受两项服务都已收敛到新合同。binding 根已按最终 ACL 创建但 junction 尚未发布时，仅精确 ACL 且为空的根
可由同一安装续建；卸载已删除 junction、尚未删除空根时，只在两项服务均 absent 且根仍精确为空时可重入退役。未知 artifact、
普通目录 child、错误 target 或 ACL 漂移一律保留现场并 fail closed。

backend 服务读取 v2 marker 与 bootstrap recovery guard 时也必须走同一个 runtime junction；SCM 不能把 guard 留在可复用的
盘符路径。marker 文件只向 backend 服务 SID 授予 ReadExecute，DataRoot 父目录同样只有遍历/读取权，不授予写入、删除、
改名或 `FILE_DELETE_CHILD`。frozen launcher 在任何业务写入前还要证明 guard 是 marker 的固定同级名称，不能只分别检查两条路径存在。

latch writer 必须先验证 data-root authority，再创建或验证机器 installer-state。首次 latch 只允许受保护
CreateNew 并复读；已有有效 current latch 时只能验证后原样返回，不得覆盖原 reason/created_at，也不得用第二次失败
重写第一份故障证据。DataRoot restore 不删除或倒退该机器 latch。失败补偿先收敛 identical legacy/current latch；已有有效
current latch 时保留原 generation/reason，不用新时间戳把可恢复双位置状态写成冲突。复制前完成备份后，已有 backend/PG
服务必须切为 disabled，并保持到复制后的安装流程显式重建服务合同；复制前失败才恢复原策略和运行态。复制后的 backend
SCM 记录也先保持 disabled，runtime guard durable 后才转 demand-start 供安装期受控启动。只有持久安装身份写入成功、lifecycle receipt 已原子进入 install_completed 且复读通过后，
提交步骤才幂等提升 PostgreSQL/backend 为 delayed-auto；提升全部成功后同版或更新 installer 才能清除 latch。
提交重试必须识别已完成 receipt，并继续尚未完成的服务策略提升与 latch 退役。
正式安装/升级 mutation 只接受持有机器生命周期锁的 Inno owner PID 和非空 lifecycle receipt；独立调用
`install_bundled_services.ps1` 只保留只读验证模式，不能自行写持久身份、提升自启或清除 recovery barrier。

安装事务还必须在 OS `CommonApplicationData` 动态解析出的独立 `TicketboxRuntimeState` 域发布无 secret 的
`installer-runtime-recovery-pending` 投影。该目录不得位于 DataRoot 内、包含 DataRoot 或与其重叠；目录与文件只允许
SYSTEM/Administrators FullControl，backend 服务账户只拥有 ReadExecute，不能删除、改名或替换该投影。旧 DataRoot restore
不会回滚或移除它。Shawl 的精确服务命令通过
`TICKETBOX_INSTALLER_RECOVERY_GUARD_PATH` 唯一传入路径；frozen launcher 每个 HTTP 请求以 lexical `lstat()` 逐级检查
该路径，不允许 `resolve()` 跟随 junction/symlink 后再判断。guard 存在、任一级 dangling/reparse/file-shaped、不可读取或
形态异常时，除 `/api/health/installation` 与一次性 `/api/bootstrap/owner` 外一律返回稳定的
`503 installer_recovery_pending`。因此 backend 可在 installer 完成 bootstrap/health 验证时运行，但不能在正式 commit
前对外提供普通业务能力；guard 删除后无需重启即可恢复。机器 latch/receipt 仍是决策权威，machine runtime-state guard 只是运行时
强制投影，不能授权提交或修复。`TICKETBOX_DATA_DIR` 与两类 recovery guard 路径属于宿主权威环境；backend 可写的
`app\.env` 加载后必须恢复这些宿主值，不能把 guard 置空或把进程移到另一数据根。commit 先写持久身份、完成 receipt、
复读 completed receipt，以 `InstallCommitValidated` 权威清理完整校验的 PG recovery toolset，再提升服务、退役机器 latch，
最后才删除该投影。若进程在 completed receipt 与后续步骤之间中断，下一次 repair 必须先重绑 receipt owner 并幂等续跑上述
提交步骤；只有完整续跑和复读成功后，才允许删除旧 completed receipt 并开始新事务。
backend SCM 记录首次创建或修复时必须先保持 disabled；machine runtime-state guard 创建、复读和 DataRoot ACL 收敛完成后，才允许把
backend 改为 demand-start。这样硬断电发生在注册与 guard 发布之间时，缺 guard 的 backend 仍不可启动；发生在
demand-start 之后时，guard 已经 durable。不能靠 PowerShell `catch` 补偿硬断电窗口。

默认卸载保留 DataRoot、持久安装身份、PG recovery toolset 和仍有意义的同机 repair/reinstall machine state，但不能保留
已完成 lifecycle receipt 或 backend runtime projection。卸载必须先严格分类 runtime-state，再在 backend SCM 身份仍可验证时
校验并 disabled 服务，退役普通文件 guard 与已验证为空的普通 runtime-state 目录，最后删除 backend 服务；服务已缺失而
runtime-state 不是严格 absent，或任何形态 malformed，均 fail closed，不能在无法验证 backend SID 时猜清理。
普通保留数据卸载若存在 completed receipt，先验证它，并在 backend/PG 服务均删除后退役，使重装开启新事务而不是续跑旧 commit；
receipt 缺失只作为旧版保留数据卸载兼容，不授权 `-DeleteData`。显式 `-DeleteData` 必须先在 DataRoot
仍可验证时预检 installer-state 的精确 ACL、已知文件集合和 InstallDir/DataRoot 绑定。停服并验证 completed
lifecycle receipt 后，先以 CreateNew 写入受保护 `delete-data-in-progress.json`，绑定 InstallDir、DataRoot 与 completed
receipt SHA-256；意图复读成功后才退役 receipt，再删除可能承载其 backup evidence 的 DataRoot。receipt 缺失时
只有该绑定意图能证明这是前次删除尝试的续跑，否则 fail closed；所有 absent/intent 分支都先以 no-follow 分类 receipt，
目录、reparse、dangling junction 或损坏 receipt 不能冒充“已退役”。identity 已部分或全部删除时，retry-authority resolver
只读解析 intent/receipt/installer-state 并重建内存路径绑定；空 retired installer-state 的 staging 与目录必须等 machine runtime
projection fail-closed 校验通过后才允许退役，失败前不得改变任何机器权威证据。
完整身份路径同样先只读验证 installer-state，再校验 runtime projection；只有 projection 通过后才清理受保护 staging、保存/收敛
PG recovery toolset 或进入服务/receipt/identity mutation。为取得生命周期互斥而清理机器锁目录中严格命名、非权威的临时 writer
残留属于 lock hygiene，不得扩大成 receipt、intent、identity 或 runtime-state 的提前 mutation。
DataRoot 精确删除把 `.ticketbox-data-root.json` 留到所有 payload 之后；若断电恰好发生在 marker 删除后、根目录删除前，
只有已复读的机器 delete intent 可以授权删除仍为空的 markerless 根，非空残树继续 fail closed。DataRoot 删除后先清理
恢复工具：完整 toolset 校验通过后才 CreateNew 发布受保护 `DELETE_IN_PROGRESS.json`，精确删除把它留到最后；重试只接受
该有效 latch，或 latch 已删后的空恢复根，不把既有 `BUILD_COMPLETE.json` 直接冒充删除授权。随后删除注册身份，最后才删除 handoff/latch、delete intent 与空 installer-state。
若注册身份已部分或全部退役，续跑只能从仍受保护且绑定 InstallDir 的 intent 恢复 DataRoot；若断电发生在 intent
退役与空目录删除之间，只允许在 runtime projection 通过后清理已验证为空的 installer-state，不重新猜测数据目标。这样 receipt、DataRoot、
registry 或 state 任一边界后断电都能收敛。未知 state 或无 marker 绑定的 current credential 不得随数据静默删除。

PG recovery toolset 的临时发布目录使用严格的 `.postgresql-recovery-staging-<pid>-<32 hex>` 命名，并从首次可见起
具有最终保护 ACL。每次持锁 save/remove 都按 Windows 大小写不敏感命名空间发现机器生命周期根直属候选，再只允许名称
以精确大小写和完整格式匹配、普通目录、非 reparse、精确 ACL 全部成立的项被清理。大小写变体会被发现后拒绝，不会因枚举
大小写敏感而静默留在权威根；近似名称、嵌套路径或 ACL 漂移同样中止。硬终止留下的可信 partial staging 因而可重入收敛，
而清理逻辑不会扩大为机器根通配删除器。
repair 临时 PG service 获得 recovery toolset ReadExecute 后，外层 toolset ACL、completion 读取和 payload 复核必须始终携带
同一个服务 SID；备份完成后先停删服务再退役 SID。任何内部 reader 以空 allowlist 重验都会把合法账户误判成越权并可能遗留
仍写 `pgdata` 的孤儿服务，因此禁止局部默认参数覆盖外层已验证 ACL 合同。
临时服务删除与 SID 退役是可中断的两阶段转换：服务已删除后仍必须通过 `sc.exe showsid` 从服务名确定性导出虚拟 SID，逐个接受
且只接受“精确 clean”或“精确 clean + 该 SID”的 DataRoot/pgdata/toolset 过渡 ACL，再幂等移除 SID 并复核 clean 终态。
不能因 SCM 记录已 absent 就提前返回。recovery toolset 根及其 delete latch/staging 的存在性必须全部来自 no-follow entry
分类；dangling junction、symlink、file-shaped root 或不可判定形态不能冒充 absent，也不能授权退役 receipt/guard。

### [ADR-0074-C05] 当前回滚是前滚 repair

迁移后，旧 installer 不认识机器 installer-state，直接恢复 N-1 EXE/脚本可能漏看 handoff 或 repair latch。
因此本切片不承诺 N-1 二进制降级；失败路径是保持服务 disabled/stopped，并由同版或更新 installer 前滚 repair。

若产品要求真正自动 rollback，后继切片必须同时提供版本化程序目录、schema compatibility gate、受验证的
数据库/文件恢复点、服务配置切换和故障注入。只恢复 EXE 或只存在 pg_dump 不算回滚。

### [ADR-0074-C06] 拓扑扩展合同

当前机器根是单正式安装权威。出现以下任一需求必须建立后继 ADR：

- 同一 Windows 主机运行多套正式实例；
- DataRoot 跨机器认领、灾难恢复或主动迁移；
- 自建 Linux/systemd、云托管、远程数据库或多 writer；
- GUI 远程管理多台服务端；
- IPv6 loopback、LAN/global IPv6 或 dual-stack。

多实例不能只新增 installations\<guid> 目录。必须同一迁移切片一起命名空间化 installation ID、global/
per-install lock、receipt、HKLM registry、SCM 服务名、端口、state 路径、GUI 实例选择和卸载归属，并定义
旧 singleton 状态的唯一认领、冲突拒绝与退役窗口。

未来 Linux 部署保持 FastAPI domain/application、API、PostgreSQL model/migration、鉴权账本边界和 storage
contract；新增 systemd、Linux filesystem/config/secret adapter 和部署包。Windows registry、PowerShell、
SCM、Inno 路径不得进入领域核心。本文不声称 Linux/cloud 已经只需替换 adapter。

IPv6 按 ::1 本机管理闭环先行，再决定 LAN/global。启用时必须在一个切片同时更新 bind 规范化、带方括号
URL、health/Host 校验、Owner Console、Cloudflare 入口、GUI 展示，以及 Android/iOS 绑定配置；只放开一个
消费者必须 fail closed。

交付顺序固定为：本安装安全包 -> Desktop source runtime -> service helper -> 发布资格包 -> GUI/EXE 小白闭环。
Linux、多云、多实例和 IPv6 在触发后继 ADR 前只保留可执行的边界与迁移条件，不得提前挤占 GUI/EXE 验收。

### [ADR-0074-C07] ADR 修订关系不制造永久假债

`amends` 表示后继 ADR 只覆盖 predecessor 的明确 scope；聚合视图必须保守地保留 predecessor 未被覆盖的验证状态。
若新决策完整替代旧合同并承担其剩余验证义务，必须使用 `supersedes`，不能靠扩大 `amends` scope 假装历史债已关闭。
accepted 文档本身不无痕改写；纠错、追加证据和新关系通过后继 ADR 或生成视图表达。这样禁止改史，但不禁止用明确的
replacement 关闭 predecessor 债务，也不要求日常新增 ADR 维护多套手工哈希真源。
ADR 编号同样不得维护“当前最大编号”手工副本；解析器根据实际 ADR 集合和保留号生成 next ID，README 只展示该派生结果。

### [ADR-0074-C08] 发布审计必须证明比较基线可读

安装器变更是否触发结构债 ratchet 只能相对一个实际可读取、且位于当前变更之前的 Git 基线裁决。显式
`XPJ_AUDIT_BASE_REF`、`GITHUB_BASE_REF`、`GITHUB_SHA`，或 `CI` / `GITHUB_ACTIONS` / `GITEA_ACTIONS` 任一上下文存在时，
基线无法解析、读取、比较，或不是当前 HEAD 的严格祖先，都必须使 release audit 失败。`pull_request` 与
`workflow_dispatch` 的显式输入还必须等于当前 HEAD 与受信任默认分支的 canonical divergence base；`HEAD` 自比较和任意
远古祖先都不合格。默认分支 push 使用事件提供的变更前 `before`；非默认工作分支 push 无论 `before` 是否全零，都必须相对
受信任默认分支计算 canonical merge-base，不能用该工作分支自己的上一 tip 隐藏更早的分支差异。首推的全零 `before` 只能在
push 上下文按同一规则求解，其他全零输入失败。
canonical merge-base 必须唯一；`git merge-base --all` 得到零个或多个最佳共同祖先时都失败，不能任取一个。任何自动化上下文中，
受信任默认分支 ref 已等于当前 HEAD 都表示缺少独立比较权威，必须失败；`HEAD^1` fallback 只允许无 CI marker 的本地探索。
若受信任默认分支 ref 已经指向当前 HEAD（默认分支首次建立/删除重建，或没有独立 pre-push authority），全零输入必须失败，
不能退化到 `HEAD^1`，否则替换历史中更早的提交会被错误吞入比较基线。
只有不带 exact ref、也没有任何 CI 标记的真实本地探索运行，才允许跳过 ratchet 并明确报告原因。本地脏工作树只有在
当前 HEAD 精确等于受信任的 remote-tracking 默认分支 tip 时，才可把 HEAD 当作未提交变更的 pre-change base；任意本地
`refs/heads/main`、带独有提交的 feature branch 或旧 remote tip 都不能借“dirty”把比较退化成 HEAD 自比较。
base resolver 返回给所有 `git show` / `git ls-tree` 消费者的 `ref` 必须是实际 Git 可解析的 commit/ref；“由 merge-base 求得”等
来源说明只能作为独立 label，不能塞进 `ref` 字段形成确定性假红。
ADR contract 和 codebase gate 必须共用同一个 CI-context predicate；event-only workflow 上下文和任何非空 marker
（包括文本 `CI=false`）都表示处于可审计自动化环境，不得因两套布尔解释分歧降级为本地 PASS。

### [ADR-0074-C09] 安装器发布复核必须带编译步骤外部锚

`BUILD_COMPLETE.json`、SHA-256 旁车和 EXE 同属一个可被协调替换的 publish unit，三者内部自洽只能证明目录完整，
不能证明它仍是本轮 ISCC 输出。编译入口必须在仍持有机器级构建锁时，把已经验证的内存中 installer SHA-256 写到 publish unit
外的 runner step output；不得在锁释放后重新读取可变的 completion/旁车来生成该值。后续 `-VerifyOnly` 必须从同一 compile step
output 显式接收并核对该值；缺失、格式错误或不匹配都失败。compile step 只能包含唯一构建命令和紧随其后的原生失败传播，不能
追加第二个 output writer。GitHub 与 Gitea 都要先验证本地 publish unit 并上传完整目录，再在 upload 后、download 前创建随机唯一且
确认为空的临时目录并以同一外部 hash 复核；下载容器名是 transport 细节，不参与发布身份，外部副本由精确文件集、version/
provenance 和 compile-step hash 裁决。上传/下载 action 固定到精确 commit。CI gap 必须按 Windows 大小写不敏感规则及
workflow < job < step 优先级解析 env，锁定 compile/pre-upload/post-download verifier 为“唯一命令 + 唯一失败传播”，并要求
动态 version resolver 完整 source 紧邻 upload、目录准备完整 source 紧邻 download，不能只搜索若干文本。这样 step 内重绑 hash/
publish path、独立改写 EXE、旁车和完成标记、覆盖 step output，或让下载与旧文件形成
union，都不能自签名通过；本文仍不把
runner 管理员攻陷或代码签名问题冒充为已解决。

## [ADR-0074-FAILURES] Threat and Failure Matrix

| 故障/威胁 | 必须结果 |
| --- | --- |
| backend/PG token 尝试读、删、改名或替换 machine state | OS ACL 拒绝；父目录也无服务账户规则 |
| 缺失 DataRoot 位于 file/reparse 祖先下 | holder 在已持句柄的祖先验证阶段拒绝；不得先发布 provisioning intent，也不得穿透创建目标 |
| 新 DataRoot 已创建但 marker 写入中断 | 路径绑定的 durable provisioning intent 保留；相同安装重试只清理严格 staging、发布并复读 marker 后退役 intent |
| 中断后用户改选 DataRoot | intent 固定原路径与 Volume GUID；拒绝自动改绑并要求同路径重试或未来显式 recovery |
| 原磁盘离线后另一卷复用相同盘符，或创建过程中发生换卷 | 首个创建回调、根句柄取得后和 marker 发布后都核对 Volume GUID；不匹配即保留 intent 并拒绝 |
| 正常运行期间原卷离线、另一卷复用相同盘符 | SCM 继续经 machine-owned junction 指向原 Volume GUID；PG/backend 不落到 replacement tree，backend 还会在任何写入前复核 marker/SCM/final-volume 三方绑定 |
| bootstrap guard 仍指向被另一卷复用的旧盘符 | SCM 合同和 frozen launcher 都要求 guard 与 marker 共享 runtime junction 根；路径不一致时在任何业务写入前拒绝 |
| 正常 runtime junction 下不存在 bootstrap recovery guard | launcher 只放行已经由 marker、SCM、InstallDir 与 Volume GUID 完整验证的精确 runtime junction；guard 缺失按正常启动处理，其他 reparse 祖先仍拒绝 |
| backend 服务读取 v2 marker | marker 只授予该服务 SID ReadExecute；写、删、改名和父目录删除权继续由 ACL 拒绝 |
| lifecycle receipt 路径相同但 marker 缺失或卷身份变化 | receipt v7 读取在任何恢复、服务或 ACL mutation 前拒绝；不得用旧 backup/阶段继续 |
| binding 根已创建、junction 尚未发布时中断 | 只允许相同安装在精确 protected ACL、空根下继续创建唯一 junction；未知 child 或 ACL 漂移拒绝 |
| PG/backend 只迁移一项 SCM runtime 路径时中断 | 受保护 post-copy receipt 下逐项接受且只接受旧/新两种完整命令合同，再确定性收敛到新别名；第三种配置拒绝 |
| 卸载已删除 junction、尚未删除 binding 根时中断 | 两项服务均 absent 且 protected 根精确为空时幂等删除根；目标 DataRoot 不被跟随删除 |
| 预先创建的 DataRoot 放入路径匹配但 ACL/owner 不可信的 marker | fresh gate 在任何 recovery service/ACL mutation 前拒绝；不得递归收编或让后续卸载删除陌生 payload |
| 低权限进程预先创建空 DataRoot 并保留写句柄 | holder 在 ready 前拒绝无 marker 空根；不得事后收紧 ACL 后继续安装 |
| fresh install 收到预先存在的非空无 marker DataRoot | prepare 在 recovery service/ACL mutation 前拒绝；不得把 legacy 候选自动认领为新安装 |
| repair/upgrade/preserved-data 收到 markerless 非空 DataRoot | 在任何 service/ACL mutation 前拒绝；不得仅凭目录形状、当前 ACL 或 `.env` 铸造 v2，未来只能走独立隔离恢复/逻辑导入 |
| frozen backend 缺任一 recovery guard、marker 或 Volume GUID 环境项 | 在创建 uploads、读取 `.env` 或导入应用前拒绝；只有非 frozen 源码模式允许不带四元宿主合同 |
| EXE、checksum 与 BUILD_COMPLETE 被协调替换 | `-VerifyOnly` 还必须匹配编译步骤在 publish unit 外保存的 installer SHA-256；内部自洽不能重新授权 |
| compile step 不写外部 hash、verifier 使用固定值或回读 BUILD_COMPLETE | CI gap 的 step/env 数据流 gate 失败；不能以字符串存在冒充同源外部锚 |
| compile step 在合法构建后再次写 GITHUB_OUTPUT | compile step source 不是“唯一构建命令 + 唯一失败传播”，CI gap 失败；后写值不能覆盖锁内 hash |
| verifier step 内以大小写变体重绑 hash，或 upload 前重绑 publish path | verifier 精确 source、Windows env precedence、紧邻 upload 的动态 resolver 任一不符即失败；不能绕开 compile-step authority |
| 上传后的安装器目录与本地已验证目录字节不同 | 下载到独立目录后使用同一 compile-step hash 的 `-VerifyOnly` 失败；外部 transport 目录名可变，但精确文件集、version/provenance 与 hash 不得变 |
| artifact 下载目录已存在、带旧文件或准备代码位于死分支/输出文本 | workflow 必须在 upload 后、download 前以独立精确步骤创建随机唯一名并确认空目录，CI gap 锁定每条语句、env 绑定与顺序；不得用下载覆盖形成联合完整目录 |
| 安装身份已删除但 machine runtime-state 仍存在或 malformed | identity-removed 重试仍先执行 runtime projection fail-closed 校验；不能跳过 guard/服务 SID 边界后报告卸载成功 |
| 悬空 lifecycle receipt junction 使原生句柄报告路径缺失 | no-follow 分类回退枚举父目录 entry 并识别 reparse，删除重试拒绝把它当作 retired |
| 低权限进程预占公开 `Global` mutex | 不影响安装器权威链；源码不创建、不等待 `AppMutex` 或公开命名 mutex，所有入口争用受保护 lifecycle holder/lock |
| 首次 pending 已存在 | CreateNew 失败，原内容不变 |
| confirmed/rebind 写入中断 | 旧完整 marker 或新完整 marker 存在；临时文件不被当权威 |
| HTTP bootstrap 写出凭据后、退役 `.env` secret 前中断 | repair 不重放 HTTP；验证 handoff 后只退役 secret 并复核服务 |
| credential 移动后崩溃 | repair 从 current credential + legacy marker 继续 |
| legacy 只有 credential，迁移任一步崩溃 | legacy 来源保留到 current marker 已绑定并复读；current-only 无来源时拒绝 |
| confirmed 后、删除 credential/marker 间崩溃 | 不再展示；重试完成清理 |
| DataRoot 被旧备份覆盖 | machine repair latch/handoff 与独立 runtime-state guard 不倒退或消失 |
| current 与 legacy 同一 artifact 内容相同 | 视为目标已发布、源待删除，复读后只删除 legacy |
| current 与 legacy 同一 artifact 内容不同 | 两者均保留，服务保持隔离并 fail closed，不自动选边 |
| 机器根/installer-state 已存在但 ACL 漂移 | 保留 ACL 与所有 state 原样并中止；不得同次修复后继续 |
| installer-state 是 junction/reparse | 拒绝读写或清理；junction 目标保持不变 |
| writer 在 rename 前断电并留下精确 staging 名称 | 持锁 repair 验证可信父目录和普通文件后清理；近似名称仍拒绝 |
| `-DeleteData` 遇到未知或错绑 machine state | 删除数据前拒绝；不得留下可误认领的静默残留 |
| receipt 的 backup 位于 DataRoot，receipt 退役后删除前崩溃 | 重试无需已删除 backup 即可继续；delete intent 保留到恢复工具和注册身份退役后 |
| DataRoot payload 已删、marker 或根删除时断电 | marker 最后删除；markerless 时只允许绑定 intent 下的空根收敛，非空拒绝 |
| PG recovery payload 部分删除后断电 | 只有完整校验后发布且最后删除的 `DELETE_IN_PROGRESS.json` 可授权续跑；无 latch 非空残树拒绝 |
| 同用户低权限进程伪造 holder release | IPC 位于机器受保护根且 release 必须回传 holder 随机 nonce；PID/可枚举文件名不足以释放 |
| holder PID 在 Inno 打开句柄前被复用 | ready 同时绑定 PID 与 creation FILETIME；`GetProcessTimes` 不匹配即拒绝，不能跟随新进程 |
| owner 在 holder 首次校验后退出且 PID 被复用 | machine/DataRoot holder 终身等待首次校验身份时取得的同一个 `SafeWaitHandle`；不重新按 PID 打开、刷新或延长新进程生命周期 |
| `{tmp}` 中同名 helper 被预放置或暂存脚本被替换 | elevated 调用只来自受保护 transient bootstrap；缺失或任一构建时 SHA-256 不匹配即中止 |
| backend 写 `.env` 清空 installer guard | launcher 恢复 SCM/宿主权威路径；普通业务仍返回 503 |
| owner 在 DataRoot holder 尚未发布 durable ready 时退出 | 启动方继续持有 operation lease；目录句柄、marker、ready 复读完成后才显式交接，否则失败路径回收 lease |
| installer 被杀且没有活动 mutation child | machine/DataRoot holder 观察 owner 退出，释放锁/目录句柄并清理自身 IPC |
| installer 被杀且 mutation child 仍持 operation lock | machine/DataRoot holder 保留权威屏障直到 child 返回；child 释放租约后再清理 IPC |
| operation lock 路径被替换为 junction、目录或其他 malformed entry | protected open 拒绝；holder 的 probe 将状态视为 active/indeterminate，保留机器/DataRoot 权威而不是释放给仍在运行的 child |
| child 以 `FileShare.None` 持有 operation lock，导致 no-follow classifier 自身抛 sharing violation | probe 将分类失败视为 active/indeterminate；holder 不得丢失机器锁或 DataRoot guard |
| DataRoot holder 在 ready 前死亡且无 acknowledgement | Setup 写入精确 abort，同步 helper 先取得 operation lock 并证明 ready absent，才清理 IPC、写入 `stopped` 并允许同进程重试 |
| DataRoot holder 在 ready 后死亡或 PID 被复用 | 同步 helper 必须同时验证 ready 的 PID/creation FILETIME/nonce、原 holder 身份已不存活且 operation lock 可取得，才能收敛停止 |
| installer 在授权 handoff child 后退出且 PID 被复用 | marker writer 使用进入机器锁时冻结的 owner identity，不重新按 PID 查询；新进程不能成为 marker owner |
| owner marker PID 已复用或 creation time 无法读取 | 独占机器锁下不把不确定 PID 当存活证据；校验其余绑定后允许受控 rebind |
| 直接运行 install service script | mutation 在任何 operation lock/服务变更前拒绝；只读验证模式仍可用 |
| receipt 缺失/损坏且没有绑定 delete-data intent | 禁止删除 DataRoot，要求 repair 恢复可验证安装事务 |
| 删除已推进到安装身份部分/全部退役后重试 | 只允许受保护且完整绑定的 delete-data intent 重建 DataRoot/PgData/AppData；空 installer-state 幂等退役，缺失/畸形 intent 或未知 state 原样保留并拒绝 |
| 已有服务 disabled 后、复制或 post-install guard 发布前 installer 被硬杀 | backend 保持 disabled，不能从已替换文件启动；下一次同版或更新 installer 前滚 repair |
| service install 成功、正式 commit 前 installer 退出 | guard durable 前 backend 保持 disabled；guard durable 后即使 backend 已运行也只放行 health/bootstrap，普通业务返回 503；下一次 repair 不误判成功 |
| receipt 已 install_completed、tool cleanup/自启/latch/guard 退役前中断 | 下一次 repair 先重绑 receipt owner 并幂等续跑全部 post-receipt commit；成功复读后才使旧 receipt 失效 |
| 正常保留数据卸载后重新安装 | guard/runtime-state 先于 backend SCM 删除而退役，服务删除后 completed receipt 退役；数据、身份和 recovery tools 保留，新安装不会续跑旧 commit |
| backend 服务已缺失但 runtime-state root/guard 仍存在或形态错位 | no-follow classifier 不把 file-shaped root、directory-shaped guard、dangling junction/symlink、不可读 entry 或其他 reparse 当 absent；拒绝在无法验证服务 SID 时猜清理 |
| PG recovery staging 发布中被硬杀 | 下一次持锁 save/remove 只清理严格命名、精确 ACL、非 reparse 的直属 partial staging；大小写变体先被发现再拒绝，其他异常项同样 fail closed |
| 临时 PG recovery 服务账户已加入 toolset ACL | 同一 ReadExecute SID 必须穿透 completion/payload 的每层校验；cleanup 先停删临时服务，再移除 SID，校验器不能拒绝自身已授权账户并留下孤儿写者 |
| 临时 PG 服务已删、SID ACL 尚未退役时进程死亡 | 重试即使看不到 SCM 记录也通过 `sc.exe showsid` 导出同一虚拟 SID，只接受 clean/clean+SID 精确过渡态并收敛到 clean |
| PG recovery root 是 dangling reparse，跟随查询显示不存在 | no-follow 分类拒绝删除或报告 absent，junction 本身及目标保持不变，receipt/guard 不得退休 |
| recovery latch 已存在后又发生不同失败 | 原 reason、created_at 与字节内容保持不变；第二次失败不能重写第一份机器权威证据 |
| push/PR release audit 无法读取声明的 exact base，或 base 不是 HEAD 严格祖先 | audit 失败并报告基线来源；不得跳过 ratchet、用 HEAD 自比较或把“未比较”标成 PASS |
| PR/manual workflow 声明 HEAD、旧祖先或非 canonical 分叉点 | 只接受当前分支与受信任默认分支的 canonical divergence base；其他可读 commit 仍拒绝 |
| 脏本地树位于 feature commit 或任意 local main | 只有 HEAD 等于受信任 remote-tracking 默认 tip 才允许以 HEAD 比较未提交变更；否则退回真实分叉基线或拒绝 |
| 新工作分支首次 push 的 `before` 为全零 object id | 仅在 push 上下文动态求受信任默认分支 merge-base；求解失败即失败，不把全零当 commit |
| 默认分支建立/重建时 `before` 为全零且默认 ref 已指向 HEAD | 因不存在独立 pre-push authority 而失败；不得使用 `HEAD^1` 隐藏替换历史中的更早提交 |
| merge-base 求解成功但 resolver 返回描述性文本而非 Git ref | 所有消费者统一收到可由 Git 解析的 exact commit；来源说明与 ref 分栏，不能让合法首推确定性假红 |
| canonical merge-base 有多个最佳共同祖先 | `merge-base --all` 结果不是唯一值即失败；不得任取一个候选缩小 ratchet 差异 |
| manual/default-branch 自动化运行时默认 ref 已等于 HEAD | 因没有独立 divergence authority 而失败；不得退回 `HEAD^1` 只审最后一条提交 |
| 只有 workflow event marker，或 `CI=false` 等非空文本 marker | ADR/codebase gate 共用同一 predicate 要求 exact base；不得被当作无 CI 的本地探索 |
| 迁移后运行旧 installer | 明确拒绝/不可发布；不得静默按 legacy 路径继续 |

## [ADR-0074-CONSEQUENCES] Consequences

- 收益：handoff/latch 与 runtime guard 均脱离 backend 删除域和 DataRoot 回滚域；SCM 运行路径还绑定原 Volume GUID，原子转换、委托租约、同路径崩溃重试与路径解析可审计。
- 成本：repair 需要维护 legacy reader 和受限双态服务迁移；机器 state、receipt、runtime junction 与 DataRoot marker 之间必须交叉校验；迁移后只能前滚 repair。
- 保留风险：真实 NT SERVICE\<backend> token 负测、clean-machine install/repair/upgrade/uninstall、
  kill/power-loss drill 和独立 recovery principal 尚未完成，故 verification 保持 unverified。

## [ADR-0074-REVERSIBILITY] Reversibility and Retirement

本目录布局可被完整的 per-install namespace 替代，但只有新协议能识别并迁移 singleton lock/receipt/state，
且旧版退役窗口和冲突路径经过故障演练后才可删除 legacy reader。未完成 handoff/latch 存在时不能靠删除
机器目录“回滚”。

反向验收：installer state 或 runtime guard 回到 DataRoot/runtime 可写树、随 DataRoot restore 倒退、默认 writer 静默覆盖 pending、
GUI/registry 单项成为安装权威、只增加 GUID 目录却不命名空间化 SCM/registry/lock，任一发生都破坏本决策。

## [ADR-0074-EVIDENCE] Verification and Evidence

| Evidence ID | 类别/状态 | 证据 | 失效条件 |
| --- | --- | --- | --- |
| ADR0074-STRUCT-01 | STRUCTURE / implemented in current tree | machine path provider、专职 lifecycle holder、不加载服务/数据库/receipt 的专用 DataRoot holder、Inno dynamic cross-check、legacy/current 分域 | 路径 provider、ACL、holder 职责或调用顺序变化 |
| ADR0074-TEST-01 | TEST / pass | Desktop 5.1/Core 7 真实行为覆盖原子目录/文件/IPC、nonce/PID、ACL drift、junction、委托 operation lease 下的 owner death、pre/post-ready holder death 收敛、独立 runtime-state ACL、PG recovery cleanup 与迁移中断；另有结构 gate 锁定 staging、completed-receipt resume、commit/autostart 和 marker-last 调用顺序 | 相关脚本、ACL、状态转换或调用顺序变化 |
| ADR0074-TEST-02 | TEST / pass | Windows packaging `91 passed`，ADR contract `64 passed`，Desktop `121 passed`，隔离 PostgreSQL backend `2532 passed`；PS5.1/Core 7 通过同一源码预检与 production-remover 故障注入，Ruff/compileall、25-counter structure gate、CI mutation gate 与 exact-base 29-lane release audit 全绿 | 最终代码、生成视图、gate 基线或测试结果变化 |
| ADR0074-BUILD-01 | BUILD / current candidate pass | 固定 CPython 3.11.15/PyInstaller 6.21.0 已生成并校验 frozen backend；固定 Inno 6.7.1、PostgreSQL 17.10、Shawl 1.9.0 已真实编译当前安装器输入。当前 dirty-worktree 候选 EXE 为 59,907,628 bytes，SHA-256 `2CA96E956B3B9FC242E60A5BD09842AC77E61F0FE8913413603DBA772A49DEA5`；canonical publish unit 与模拟 artifact 下载到 GUID 临时目录的副本均用同一 compile-step 外部 hash 通过 `-VerifyOnly`。它是代码评审候选，不冒充 clean-commit release artifact | 安装器输入、固定工具链、复审结论或 provenance 变化 |
| ADR0074-REVIEW-01 | REVIEW / CLEAN | 多轮 `gpt-5.6-sol` xhigh 只读审计发现并关闭 owner handoff 覆盖、runtime projection/no-follow、delete retry、CI exact-base、single-writer、download union、Windows env precedence、step 内 hash/path 重绑等 P1/P2；最终 lifecycle 与 CI 两个独立镜头均明确 CLEAN，无未关闭 P0-P2 | 后续修改相关 lifecycle、ACL、artifact dataflow、workflow parser 或测试故障注入 |
| ADR0074-DRILL-01 | DRILL / unrun | 真实服务 token read/delete/rename/replace 负测 | 未运行 |
| ADR0074-E2E-01 | E2E / unrun | fresh、旧布局 upgrade、kill/repair、confirm、uninstall retain/delete | 未运行 |

代码合并不等于 release verified。真实服务 token、clean-machine 和故障注入矩阵通过前，只能发布测试候选，
不能宣称安装/回滚闭环完成。

- 可执行本地门：在 backend 目录运行 python -m pytest packaging/tests -q。
- 可执行治理门：运行 python scripts/render_adr_contract_views.py，再运行
  python -m pytest tests/test_adr_contract_registry.py -q。

## [ADR-0074-REFERENCES] References

- [[0062]] Windows 安装事务、生命周期回执与复制边界。
- [[0063]] owner bootstrap committed-but-unseen 与交接 ceremony。
- [[0065]] schema-v2 ADR 冻结历史与后继修订。
- Microsoft MoveFileEx:
  <https://learn.microsoft.com/windows/win32/api/winbase/nf-winbase-movefileexw>
- Microsoft file access rights (FILE_DELETE_CHILD):
  <https://learn.microsoft.com/windows/win32/fileio/file-access-rights-constants>
- Inno Setup ExtractTemporaryFile（InitializeSetup 前置 helper 与 solid-compression 顺序合同）：
  <https://jrsoftware.org/ishelp/topic_isxfunc_extracttemporaryfile.htm>
- Inno Setup Exec（`ewNoWait` 不提供 child PID）：
  <https://jrsoftware.org/ishelp/topic_isxfunc_exec.htm>
- Inno Setup GetSHA256OfFile：
  <https://jrsoftware.org/ishelp/topic_isxfunc_getsha256offile.htm>
- docs/architecture/AUTHORITY_SOURCE_REGISTER.md 与
  docs/architecture/CORE_INVARIANTS.md。
