# 小票夹核心不变量目录

本目录是审查路由表，不是 ADR、数据库或业务真源。只有能追到 accepted ADR 和真实代码/约束的条目才算当前契约；
目标与当前实现分开。产品边界见 [[0066]]，权威身份见 [AUTHORITY_SOURCE_REGISTER](AUTHORITY_SOURCE_REGISTER.md)。

- Catalog version: `1.1.0`
- Review base: `83af67d0702a7bfda2fa3a760b56dbef47c663c7`
- Installer implementation: this tree includes [[0074]]; release verification remains explicitly incomplete
- Status semantics: `implemented | partial | nonconformant | not-started`; none of these alone means verified

## 宿主机生命周期

### INV-HOST-001 领域核心不依赖宿主 adapter

Contract：金额、账本、身份、权限、人工确认和同步协议不得依赖 SCM、注册表、PowerShell、Inno、固定路径/端口、
GUI 或 Windows 文件系统。Windows 是当前 adapter；Linux/cloud 只新增 adapter。Related：[[0047]], [[0066]]。

Current：**partial**。核心模型大体独立；architecture/runbook 和部分 service 仍带 loopback/Windows 假设。

### INV-HOST-002 一次只有一个受证明的 runtime/migration writer

Contract：当前 topology 只支持一套 active backend writer；启动必须证明 process/build/config/schema/DB identity。
迁移由短命 migrator 串行，旧 writer 在任何 DDL 前隔离。Related：[[0062]], [[0067]]。

Current：**partial / unverified**。backend 已在 Alembic 写入前完成 schema inspection、compatibility 和既有库备份；
installer overlay 已在 Inno `ssInstall` 复制前把 program-files boundary 持久化，并以专用 DataRoot holder +
operation lease 分离长命目录权威与短命升级准备；正式 backend 的 marker/guard 读取统一经过 Volume GUID runtime projection，
marker 仅授予服务 SID 读取权。单 writer 的 clean-machine、kill/power-loss 与真实服务运行验证仍缺，
不能升级为 verified。

### INV-HOST-003 GUI、provider 和单个任务不在关键运行链

Contract：GUI 崩溃、OCR/AI provider 失败或单任务异常不能停止 PostgreSQL/backend 或阻断手工记账；资源耗尽有背压。
Related：[[0015]], [[0047]], [[0072]]。

Current：**partial/nonconformant**。provider fail-open 基本成立；task claim/restart/backpressure 未闭环。

### INV-HOST-004 发布 gate 不得把未比较降级为通过

Contract：显式 exact base 或任一 CI/PR 上下文存在时，release audit 必须读取并比较该基线；CI base 必须是 HEAD 的
严格变更前祖先。PR/manual workflow 只接受当前分支与受信任默认分支的 canonical divergence base；默认分支 push 使用事件
`before`，非默认工作分支 push 无论是否首推都必须相对受信任默认分支求 canonical merge-base，不能用工作分支上一 tip 隐藏
较早差异。首推的全零 `before` 只允许在 push 上下文按同一规则求解；默认 ref 已指向 HEAD 时因缺少独立 pre-push authority 而失败，
不得退化到 `HEAD^1`；该 fallback 只允许无 CI marker 的本地探索。canonical merge-base 必须唯一，多最佳共同祖先直接失败。
本地脏树只有 HEAD 等于受信任 remote-tracking 默认 tip 时才可用 HEAD 比较未提交变更。解析、读取或
祖先资格失败即失败。只有没有 exact ref、没有 CI 标记的真实本地探索运行可明确跳过 ratchet。resolver 交给
`git show` / `git ls-tree` 的 base 必须是实际可解析
commit/ref，来源说明不得混入 ref。ADR/codebase gate 共用同一 CI-context predicate；event-only 上下文或
任何非空 marker（包括 `CI=false`）都不得降级为本地 PASS。Related：[[0074]]。

Current：**implemented in current tree / unverified in cloud**。exact-ref、GitHub/Gitea push/manual/PR 上下文已统一 fail closed；
最终 PR head 的云端 lane 尚未运行。

## 账本权威与家庭身份

### INV-LEDGER-001 所有业务事实按 ledger 隔离

Contract：每次读写以当前有效 principal + ledger membership + ledger-scoped query/service 裁决；全局 public ID、account 或
本机访问不能跨账本。PostgreSQL 是结构化账务事实唯一在线权威。Related：[[0005]], [[0066]], [[0068]]。

Current：**partial**。大多数 service/query 已 scoped；Owner Console 隐式 owner 与部分管理路径仍模糊。

### INV-LEDGER-002 一个账本只有一个一致的 active owner

Contract：每账本恰有一个 active `LedgerMember(role=owner)`，它是 owner capability 的 canonical source；
`Ledger.owner_account_id` 仅是受约束兼容投影，不得独立授权。两者由数据库约束、同事务 transfer 和可证明的 repair invariant
保持一致；transfer 立即撤销旧 owner-only capability。Related：[[0068]]。

Current：**nonconformant**。`Ledger.owner_account_id` 与 `LedgerMember(role=owner)` 是双表示，无 DB 级唯一 active owner/一致性约束。

### INV-ID-001 principal、role、credential scope 与 recovery capability 分离

Contract：Account/Device/app session/Web session/UploadLink/admin/bootstrap/recovery 不互换；loopback、Cloudflare Access 和 OS admin
不能替代 ledger authorization。独立 recovery principal 不随数据库 generation 回滚，只能经受审计 ceremony 为 canonical owner
签发一次短期 re-enrollment，不能变成长期 admin 或账本写入口。Related：[[0028]], [[0059]], [[0063]], [[0068]]。

Current：**nonconformant**。日常 app/upload scope 大体分离；public-admin escape hatch、Owner Console 隐式 owner、restore sanitation未闭环。

### INV-ID-002 撤销、过期、transfer 和 restore 不得复活旧能力

Contract：旧 bearer/one-shot/UploadLink/CSRF key 在 revoke/expiry/transfer/clone 后按 policy 失效；恢复同一 ceremony 不得延寿已过期入口。
same-install sanitation 撤销回滚能力后，只能通过独立 recovery principal 显式重登记 canonical owner，不能回退到旧凭证或“第一个 Account”。

Current：**nonconformant**。installer overlay bootstrap recovery 会重设 UploadLink expiry；main restore runbook仍期望旧 token可用。

## 财务事实与投影

### INV-FACT-001 suggestion、计划、当前事实、事件和投影不可混称

Contract：OCR/AI 是 suggestion；Budget/Goal 是可修订计划；Expense 是当前账务 aggregate；Debt 余额来自母对象+事件；报表/status/
items_sum 是投影。只有明确用户命令和后端 transaction 能改变权威事实。Related：[[0035]], [[0049]], [[0060]], [[0066]]。

Current：**partial**。主要写边界成立；confirmed Expense 可原地改且修订事实/审计不完整，Debt rebuild仍依赖 mutable status。

### INV-FACT-002 财务修订、冲销和退款必须显式

Contract：确认后更正记录 actor/reason/old/new/OCC；退款/chargeback/reversal 是 linked fact，不用负 Expense、discount 或删除偷换；
拒绝、归档、软删、void、forgiveness 各有独立语义。

Current：**not-started/partial**。授权更正存在但缺统一 revision fact；退款通知被忽略，尚无正式 reversal 模型。

### INV-FACT-003 投影可由权威事实确定性重建

Contract：删除 projection/cache 后能重建相同 minor-unit totals/status，repair dry-run/计数/差异/幂等；不可从可变投影反推事实。

Current：**nonconformant** for Debt void rebuild；Expense/report主要可重算但缺统一灾难演练。

### INV-FACT-004 回收站不是隐私擦除或事实反转

Contract：recycle/restore 是在线可逆状态；备份保留、审计、财务 correction/reversal 与永久数据擦除分别裁决。
Related：[[0051]], [[0052]]。

Current：**partial**。在线恢复已实现；备份 purge、ABA/代次和隐私承诺未统一。

### INV-FACT-005 事实类型按投影归属去重

Contract：ledger spending、household consolidated spending、cash movement、liability 与 gross/refund/net 各有显式输入矩阵。跨账本
split/invitation 的 source/receiver Expense 共享 household economic-event identity，家庭合并只计一次；Debt repayment 可改负债/资金移动，
不得再算购买支出。Related：[[0029]], [[0049]], [[0073]]。

Current：**current reports are ledger-scoped; household consolidation not implemented**。跨账本 source/receiver 与 Debt 已可同时创建，但仓库尚无
household economic-event identity、投影注册表和 double-count golden test；因此引入家庭合并报表前必须先补这些边界，不能把现状称为已覆盖。

## 金额与货币

### INV-MONEY-001 权威金额禁止 binary float，并有明确宽度

Contract：持久/聚合金额使用 signed 64-bit minor units（或更强精确整数），FX 中间值用 Decimal；客户端/JSON/UI 不经 float/Double。
应用上限必须小于 DB 类型上限并在所有入口一致。Related：[[0001]], [[0061]]。

Current：**nonconformant**。多数列为 PostgreSQL 32-bit Integer；部分 parser 接受超过其范围的数，Web/AI 路径仍有 float/`round()`。

### INV-MONEY-002 金额必须绑定 installation currency semantics

Contract：当前 home currency 按 [[0061]] 是 installation-global、持久、revisioned 的语义；每笔事实仍保存 currency/minor-unit/FX snapshot。
未知 currency/exponent 拒绝，不能回落 CNY 或固定 `/100`。改为 per-ledger 必须用 successor 迁移跨账本聚合与离线 payload，不能由客户端暗中选择。
Related：[[0027]], [[0061]], [[0069]], [[0073]]。

Current：**nonconformant**。home currency 仍为 env/install default，缺持久 installation binding，多端存在 CNY fallback 和 `/100`。

### INV-MONEY-003 舍入、符号和调整类型统一

Contract：major→minor/FX 的 rounding mode 由后端领域函数统一；discount/tax/repayment/forgiveness/adjustment/reversal 各有符号约束，
客户端不自定。Related：[[0035]], [[0049]], [[0061]]。

Current：**nonconformant**。核心 FX 使用 ROUND_HALF_UP，但部分 Web Decimal 默认 half-even、AI 路径使用 float/round。

### INV-MONEY-004 服务端冻结 FX snapshot

Contract：客户端提交原币、原金额、事件语义；后端按发生日/规则选择 rate 并冻结 snapshot。缺率保持 pending，刷新 rate 不重算已确认事实。

Current：**implemented for backend online path / partial end-to-end**；Android 离线和 capability/currency binding仍不安全。

## 时间与账务日历

### INV-TIME-001 瞬时、账务日期、展示和审计时间分离

Contract：event time 是带 precision 的 tagged representation；时刻已知时必须是带 offset 的瞬时，只有日期/区间时不得伪造 UTC instant。
accounting date + ledger calendar revision 决定预算/报表；display zone 只展示；created/confirmed/security expiry 由服务端 UTC。Related：[[0070]], [[0073]]。

Current：**nonconformant**。当前只有 expense_time/created/confirmed，缺 accounting date/revision，query/env timezone可重切月份。

### INV-TIME-002 naive/DST/非法 zone fail closed

Contract：新 API 不猜 naive；DST gap拒绝、fold显式；offset/zone不一致拒绝。legacy adapter记录 assumed zone和退役条件。

Current：**nonconformant**。手工/CSV/OCR 对 naive 解释不同，非法 zone 会静默回 UTC。

### INV-TIME-003 设备墙钟不是安全或顺序权威

Contract：credential expiry、OCC、server audit、idempotency retention、task lease和installer deadline由服务端/单调时钟裁决；离线 intent
带 calendar revision，设备回拨不能延长重放。

Current：**partial**。服务端身份时间大体正确；Android outbox age等仍依赖设备 wall clock。

## 规范化收据、附件与缩略图

### INV-IMAGE-001 有效附件由 PG metadata 与匹配 bytes 共同成立

Contract：PG 决定 ledger/expense归属、生命周期和 expected digest；私有存储承载去元数据/重编码后的规范化 bytes。任一缺失/不匹配
都是 degraded，不自动让另一方获胜。缩略图是缓存。Related：[[0003]], [[0071]]。

Current：**nonconformant**。读取不重验 hash，DB+uploads无同代 manifest；main cleanup会把意外缺失写成已清理。

### INV-IMAGE-002 path/hash 只由后端生成且 tenant-contained

Contract：客户端不能写 path/hash；读取/清理/迁移校验 containment、ledger、ACL/reparse和打开句柄，日志不泄漏路径/PII。

Current：**implemented for normal backend path / partial Windows tamper evidence**。

### INV-IMAGE-003 缺失、损坏、删除、孤儿和恢复中可区分

Contract：五态有稳定 API/UI/metric和 repair；保护窗后才删 orphan；永久清理明示不可逆且与备份 retention协调。

Current：**nonconformant at main**。当前 ADR worktree的 cleanup修复只是未提交实现方向，不能算 baseline证据。

### INV-IMAGE-004 DB 与附件必须同代备份/恢复

Contract：generation/barrier/manifest绑定 DB dump、规范化 bytes、digest/config/identity；隔离 restore全量对账后才开放。

Current：**not-started/nonconformant**。pg_dump与 uploads mirror独立，无一致恢复点。

## AI / OCR 建议

### INV-AI-001 自动化只建议，人工命令才入账

Contract：OCR/AI/规则候选写 pending suggestion/fact，不能自动确认、改已确认字段、写预算真相或绕过权限/OCC；失败不阻断手工。

Current：**implemented for current OCR/budget advisor paths**。

### INV-AI-002 provenance 与用户 ownership 可追踪

Contract：provider/model/parser/algorithm version、evidence hash、field ownership和用户修订可追；retry只改仍属自动 ownership 的 pending字段。

Current：**partial**。provider/model/fact已有；独立 parser version、DB append/retention强制和并发单飞不足。

### INV-AI-003 provider-by-provider 最小外发

Contract：RapidOCR进程内、loopback local LLM、可能公网的 Budget Advisor分别登记可见字段、网络、retention、日志和关闭行为；一个 provider
的 allowlist不能证明所有 AI 合规。收据/债务原图当前只允许 local-loopback vision；远程原图 provider 必须先有独立 accepted 隐私/安全决策和用户知情。
Related：[[0015]], [[0036]], [[0037]], [[0073]]。

Current：**partial**。Budget Advisor allowlist较强；OCR/debt image provider的统一登记和诊断脱敏仍缺。

## 多端写入与离线冲突

### INV-SYNC-001 PG committed fact 与本地 intent/cache 分离

Contract：Room confirmed可删重建；outbox是设备/ledger binding未提交 intent；每个 offline-capable command 在首次网络调用前先原子持久化
intent/idempotency key，再由统一 dispatcher 发送；成功后PG结果胜。Web当前只缓存静态资源，不是持久离线 writer。
Related：[[0038]], [[0069]]。

Current：**nonconformant**。10→11 migration和logout/switch可清 outbox；ExpenseDetailRepository 仍 direct-first、IOException 后才 enqueue。

### INV-SYNC-002 OCC 与 idempotency 各守一层

Contract：row_version防不同意图丢更新；intent key处理同一意图committed-but-unseen。same key返回稳定首次结果并绑定 principal/device；
KeepMine是新意图/新key。Related：[[0042]], [[0057]], [[0069]]。

Current：**nonconformant**。server idempotency无稳定 envelope/principal binding且允许 stale reclaim。

### INV-SYNC-003 payload、identity 与 ledger semantic revision显式

Contract：持久 intent包含 payload schema、API contract、principal/session、ledger binding、currency/calendar revision；unknown版本 quarantine/
upgrade-required，不按默认值猜。旧/新 client/backend有能力握手。

Current：**nonconformant**。当前 row缺这些 revision，auth/status无最低客户端或 capability envelope。

### INV-SYNC-004 删除/merge/void按聚合语义防 ABA

Contract：每个 aggregate定义 tombstone/generation/OCC/restore/compensation；不强迫 Expense reject、rule delete、tag merge、Debt void 共用一个状态机。

Current：**partial**。部分 soft delete/OCC存在，统一 generation/旧 outbox ABA未闭环。

## 安装、升级与数据恢复

### INV-RECOVERY-001 backup 是候选，验证后才晋升

Contract：DB、附件、semantic config、identity和必要恢复材料绑定同 generation；不随 DB 回滚的 recovery root/epoch 也必须可验证地绑定
installation/generation。隔离 restore 校验 schema、财务总额、owner/membership、digest、旧 credential sanitation 和 owner re-enrollment。
`pg_restore --list`、文件存在或health=ok均不够。Related：[[0059]], [[0062]], [[0067]], [[0071]]。

Current：**nonconformant**。

### INV-RECOVERY-002 日常运行凭证与恢复根隔离

Contract：backend/PG服务账户不能读取、删除、改名或替换 owner handoff/recovery root/clone/rollback 材料；其父目录也不得给 backend
write、`DELETE_CHILD` 或 FullControl。bootstrap challenge 只是短命 backend-readable 安装凭证；restore/clone 前轮换适用 secret，
并在开放 listener 前证明旧能力失效和 recovery re-enrollment 可用。Related：[[0059]], [[0063]], [[0068]]。

Current：**partial**。owner handoff/recovery latch 已迁入机器生命周期根下受保护的 `installer-state`，
backend/PG 对其父目录也没有访问权；独立 sealed recovery principal/epoch 与真实服务账户负测仍缺。Related：[[0074]]。

### INV-RECOVERY-003 migration/install跨过 no-return point前必须有恢复点

Contract：先持久化状态/锁/backup，再允许DDL或文件覆盖；断电后能区分pre-copy/pre-DDL可补偿与post-boundary repair/forward-only。

Current：**partial / unverified**。backend inspect -> compatibility -> backup -> Alembic 与 Inno 复制前持久 boundary 已接线；
机器根由专职 holder 先验证后持锁，IPC 留在受保护根并以随机 nonce 防重放。lifecycle owner 与 holder ready 都绑定 PID + Windows
process creation FILETIME；machine/DataRoot holder 打开并校验 owner 的同一个 `SafeWaitHandle` 后终身等待它，不按 PID 重开或
刷新，Inno 用 `GetProcessTimes` 排除 ready 前 PID 重用；mutation child 以 operation lock 取得委托租约，DataRoot holder
只有在目录句柄、marker、ready 均 durable 且复读后才显式接过启动 lease，owner 死亡时 machine/DataRoot holder 会保留到活动 child
返回。operation lock 必须是 no-follow 普通受保护文件；malformed/reparse/不可读形态视为 active/indeterminate，不能使 holder
提前释放权威。holder 启动或 preflight 失败时，Setup 只有在目录 guard 与 operation lease 已释放、且 holder 向同一活 owner
原子提交并复读 `stopped` 后才可清空状态并同进程重试。DataRoot 缺失目录链以最终 ACL 原子创建；holder 在锁住可信祖先后、
首个目录可见前 durable 发布绑定路径与 Windows Volume GUID 的 provisioning intent；`ticketbox-data-root-v2` marker 以最终
ACL/owner 的受保护 writer 发布，并永久绑定 DataRoot、InstallDir 与同一 Volume GUID。fresh gate 在任何 recovery-service/ACL
mutation 前同时验证根 ACL、marker no-follow 形态、精确 ACL/owner 与完整 v2 绑定；预先存在的无 marker 空根、v1 marker 或伪造
marker 均拒绝事后收编，中断重试只恢复相同路径、同 Volume GUID intent 下的精确 ACL 空根和严格 staging。卷身份在首个创建回调、
根句柄取得后和 v2 marker 复读后重复核对，marker 与当前卷一致后才退役 intent；中断后改选路径不自动改绑，盘符复用或任何
不可判定状态继续绑定原路径并 fail closed。旧 v1 可在既有安装证据下原子迁移；markerless 非空布局在所有普通安装模式都拒绝，
不能通过当前 ACL 或目录形状重铸权威，只能由未来独立隔离恢复/逻辑导入生成新的受保护 DataRoot。
机器 lifecycle receipt v7 固化同一 `data_volume_identity`，每次 stale recovery/commit/uninstall 都在 mutation 前复核 receipt、v2 marker
与当前挂载卷。正式 PG/backend SCM 通过 OS `CommonApplicationData` 下 machine-owned、服务只读的稳定 junction 指向该 Volume GUID
DataRoot；frozen launcher 在任何写入前要求两类 guard、marker、Volume GUID 四项完整，拒绝 reparse marker，并要求 marker 的 DataRoot 等于 junction 最终目标、InstallDir 等于 frozen executable 根、
Volume GUID 与 SCM/final path 一致。原卷离线或盘符被复用时不会落入 replacement tree。binding 根创建、单服务迁移、junction 退役三个断点只允许精确空根和
旧直连/新别名两种完整命令合同收敛，不能把宽松 argv 或第三种路径当 repair。
bootstrap recovery guard 必须与 marker 同处这个已经完整验证的 runtime junction；guard 缺失时只允许该精确 junction 祖先，
任意其他 reparse、dangling 或不可读祖先仍 fail closed，避免把正式投影误判为攻击路径或反向放宽通用 guard 检查。
backend-readable runtime guard 位于 OS 动态解析、与 DataRoot 不相交的 machine runtime-state 域；PowerShell no-follow entry
inspection 与 launcher lexical `lstat()` 都不把 file-shaped root、directory-shaped guard、dangling junction/symlink、不可读 entry
或其他 reparse 当 absent，DataRoot restore 不能移除阻断投影。复制前已有服务先 disabled；复制后的 backend 也保持
disabled，直到 runtime guard durable 才转 demand-start。普通保留数据卸载在 backend SID 仍可验证时先移除 guard/空 runtime-state，
服务删除后退役 completed receipt，同时保留数据、安装身份与 PG recovery tools。identity 已部分/全部删除的 retry resolver
必须先 no-follow 分类 receipt 且保持只读；machine runtime projection 验证通过前不得退役空 installer-state。完整身份卸载也必须在
projection 前保持 installer-state 与 PG recovery 只读；严格命名的 lock-writer 临时残留清理不授权业务权威迁移。
DataRoot/PG recovery 删除把受保护 authority/latch 留到最后，仅在已验证 delete intent 下收敛空根；PG recovery staging 先按 Windows 大小写不敏感命名空间发现，再只清理精确命名、
精确 ACL 的可信 partial staging；临时 PG 服务账户的 ReadExecute SID 必须贯穿 completion/payload 校验，并在停删服务后才退役。
服务已删除后仍由服务名确定性导出虚拟 SID，只接受 clean/clean+SID 精确过渡 ACL 并幂等退役；PG recovery root 的 dangling
reparse/file-shaped/不可判定形态不能冒充 absent。completed receipt 的 post-commit 步骤可幂等续跑；clean-machine
kill/power-loss/repair 演练仍缺。Related：[[0062]], [[0074]]。

## 维护规则

新 invariant 必须先有真实事故/风险/消费者和 ADR；目录只引用，不自行决定。实现状态变化引用代码提交和审查日期；未提交 overlay
必须单独标注。任何“路径存在”只算结构关联，不能把状态升级为 verified。
