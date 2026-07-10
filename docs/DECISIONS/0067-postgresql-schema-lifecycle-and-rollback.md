+++
schema_version = 2
id = "0067"
title = "PostgreSQL schema 生命周期：先兼容、后备份、单迁移者升级与可证明恢复"
summary = "结构化账本只有在只读检查、兼容性裁决、已验证恢复点、单迁移者 Alembic 和幂等 seed 全部成功后才可开放写入"
current_scope = "PostgreSQL 权威账本的首次建库、schema 升级、mixed-version、应用回退、数据库恢复和未来宿主适配；不再沿用 SQLite 文件切换协议"
date = "2026-07-11"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "migration-retirement"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "后端数据层与宿主生命周期维护者"
verification_owner = "独立数据正确性/恢复 reviewer + PostgreSQL CI"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "supersedes"
target = "0031"
scope = "PostgreSQL-only 现行 schema 初始化、升级、兼容、回退与恢复范围；0031 的 SQLite cut-over 仅保留为历史"

[[relations]]
kind = "refines"
target = "0041"
scope = "Alembic schema 权威、迁移权限、pre-DDL backup、binary/schema compatibility 与 PostgreSQL 回退语义"

[[relations]]
kind = "refines"
target = "0066"
scope = "家庭账务事实系统中安装升级与恢复承重域的 PostgreSQL schema 子协议"

[[relations]]
kind = "depends-on"
target = "0062"
scope = "宿主升级必须先隔离旧 writer、持有生命周期锁并把数据库结果绑定到安装回执"
+++
# 0067 PostgreSQL schema 生命周期：先兼容、后备份、单迁移者升级与可证明恢复

## [ADR-0067-SCOPE] Context, Scope and Non-goals

小票夹现在是家庭账务事实系统，不是早期的单机小票上传器。PostgreSQL 承载账本、家庭身份、权限、财务事实、
离线命令结果、审计和状态机；Windows 安装器、源码运行、未来 Linux/云端宿主都可能启动同一 backend，而 Android、
Web 和长期离线 outbox 又会跨版本继续产生写入。因此 schema 生命周期必须保护的是**持续演进的权威账本**，不能再
依赖 SQLite 文件复制、同 release 同时升级或“通常只启动一个进程”的假设。

当前启动路径与这个边界相反：`app.database.init_db()` 先调用 `Base.metadata.create_all()`，随后才推断/写入
Alembic baseline、决定是否备份并执行 upgrade；`app.main.lifespan()` 又在 `init_db()` 返回后才调用
`assert_binary_compatible_with_db()`。这意味着不兼容 binary、未知 pre-Alembic 数据库和待迁移数据库都可能先被
当前 ORM 改动，恢复点和 compatibility gate 失去“变更前”含义。

本 ADR 决定 PostgreSQL 首次建库、已有库升级、schema/application 回退和恢复的顺序、权限与失败语义。它不决定
Android Room schema（由客户端迁移契约负责），不恢复已退役的 SQLite cut-over 机器，也不提前支持多个 active
backend writer。单个 migration 的业务 backfill 仍应有自己的领域不变量和校验；本 ADR 只规定其不得越过的生命周期。

## [ADR-0067-ASSUMPTIONS] Assumptions and Applicability

- 当前受支持拓扑是一套 PostgreSQL、一个 active backend writer；升级窗口内旧 writer 可以被宿主协调器停止。
- PostgreSQL 是结构化业务事实唯一在线权威；Room、CSV、报表和备份都不能反向裁决 schema 或账本事实。
- 客户端可能长期离线，安装器、backend、API contract、outbox payload 与数据库 revision 不会天然同版。
- PostgreSQL 允许事务化多数 DDL，但 backfill、`CREATE INDEX CONCURRENTLY` 等步骤可能跨事务；migration 必须声明。
- 首装可以没有业务数据；只要存在应用表、未知对象、账本/身份行或无法证明为空，就按“已有数据”处理。
- 当前单 writer 前提一旦失效（多宿主、多 active backend、rolling deploy），在共享 fencing/version-skew 契约落地前
  必须拒绝自动迁移，不能把本 ADR 的宿主停服假设外推到多实例。

## [ADR-0067-DRIVERS] Decision Drivers

- 数据正确性：任何 DDL、backfill 或 seed 之前先证明 binary 可以解释当前数据库，并保留可恢复的变更前状态。
- 权限隔离：长期处理公网/局域网请求的 runtime 身份不应同时持有任意 ALTER/CREATE/DROP 权限。
- 可恢复性：应用回退、事务回滚、前滚修复和整库恢复是四种不同动作，不能用“有 dump”混为一个 rollback。
- mixed-version：旧客户端、旧 outbox 和新旧 backend 对同一 schema 形态的读写能力必须显式证明。
- 宿主可替换：Windows 可用 SCM/Inno/PowerShell 隔离 writer，但核心协议不能依赖注册表、固定路径或 GUI。
- 可操作性：失败必须停在可识别状态，告诉 owner 是否改过 schema、是否可重试、需要前滚还是恢复。
- 性能与资源：家庭自托管不能因无限等待锁、无磁盘预算或不可预测全表 backfill 被静默停机。

## [ADR-0067-ALTERNATIVES] Alternatives

- **A. 保留 `create_all → stamp/infer → backup → Alembic` 兼容桥**：首装方便，但当前 ORM 会在历史 revision 和
  compatibility 判定前改变数据库；拒绝。
- **B. backend 永不自动迁移，只由维护者手工执行 Alembic**：权限面较窄，但普通家庭升级容易漏备份、用错库或在
  writer 活跃时运行；若无同一机器协议和回执，只是把风险转给用户；拒绝作为默认，可保留为受控 repair 入口。
- **C. 宿主协调的单迁移者状态机**：只读检查和兼容裁决先行，已有库先取得已验证恢复点，再由短命 migrator 执行
  Alembic，验证和 seed 成功后才开放 runtime writer；选定。
- **D. 每次升级都新建 PostgreSQL shadow database，验证后切换连接**：隔离强，但需要双倍存储、连接/身份切换和
  跨库增量协议；当前单机停机窗口没有对应收益。若未来数据库规模或零停机需求出现，可作为替代方案复审。

## [ADR-0067-DECISION] Decision

选择 C。数据库生命周期是一个 fail-closed 状态机；`READY` 之前没有业务 HTTP writer、后台任务或 provider 回写。
Alembic revision 是物理 schema 的唯一执行权威，compatibility metadata 只描述可解释范围，不能代替真实 revision。

### [ADR-0067-C01] Alembic 是 runtime schema 唯一写入者

- 首次建库和既有库升级都必须从 Alembic revision graph 到达目标 head。生产/runtime 路径禁止调用
  `Base.metadata.create_all()`、手写 `CREATE TABLE IF NOT EXISTS` 或按当前 ORM shape 猜历史 revision。
- `Base.metadata` 只用于 ORM 映射、autogenerate review 和 schema 对照测试；它不是对已有库的隐式迁移器。
- `alembic_version` 是物理 revision 权威；`app_meta.schema_version` 与 `schema_min_compatible` 是语义兼容元数据，
  必须由对应 migration 在受控事务中推进，不能按 `BACKEND_VERSION` 启动时自动补写。
- `schema_migrations`、安装回执和日志只能作审计/恢复证据；它们不得把未到达的 Alembic revision 宣称为已应用。
- 存在应用表但缺少合法 Alembic lineage 的库属于 `UNKNOWN/ADOPTION_REQUIRED`。不得依据某一列是否存在自动 stamp；
  必须使用针对已知来源、可校验且先备份的 adoption migration。来源无法证明时保持只读/repair，禁止启动 writer。

### [ADR-0067-C02] 顺序固定为 inspect → compatibility → backup → Alembic → seed

宿主或 pre-runtime coordinator 必须按以下顺序执行，任一步失败都不得跳到后一步：

1. 有界等待 PostgreSQL 可连接，并取得本数据库唯一 migration lease；
2. **只读 inspect**：读取数据库 identity、现有对象、Alembic heads、兼容元数据和是否确实为空，不执行 DDL/DML；
3. **compatibility**：把数据库分类为 empty、managed-compatible、behind-with-supported-path、newer-than-binary、
   unknown-lineage 或 invalid；后两类及未知 lineage 一律 fail closed；
4. 对含任何既有应用状态的库创建并验证 **pre-DDL recovery point**；empty 库明确记录 N/A；
5. 使用声明的 migration plan 执行 `alembic upgrade <target-head>`；
6. 校验 revision、兼容元数据、migration-specific 数据不变量和 runtime role 权限；
7. 在 schema 已验证后执行可重入 seed；seed 不得执行 schema 修复或历史事实 backfill；
8. 降权/切换到 runtime 数据库身份，发布 `READY`，再开放路由、启动 scheduler/worker 和消费离线请求。

状态至少可区分 `LOCKING / INSPECTING / BACKING_UP / MIGRATING / VERIFYING / SEEDING / READY /
REPAIR_REQUIRED / REFUSED`。进程退出不能把 `MIGRATING` 或 `REPAIR_REQUIRED` 自动解释为可重新对外服务。

### [ADR-0067-C03] migration owner、runtime writer 和宿主协调者分权

- 只有短命 migrator identity 可以拥有或取得 schema DDL 权限；长期 backend runtime identity 只获得业务所需的
  table/sequence/function DML 权限，不拥有 schema，也不能 ALTER/CREATE/DROP。
- migrator 凭证不得进入 HTTP 请求上下文、普通服务长期环境、SCM 可枚举参数、日志或 runtime 可读配置。迁移完成
  后连接必须关闭；backend 以独立 runtime credential 新建连接池。
- 当前单机升级同时需要宿主生命周期锁、旧 backend 已停止的进程证据和 PostgreSQL advisory migration lock。
  任一证据缺失或发现未知 active writer/session，拒绝迁移；“端口 health 返回 200”不证明 writer 已隔离。
- advisory lock 的 key 必须稳定绑定 application + database identity，锁等待默认最多 30 秒；超时返回
  `migration_lock_busy`，不抢锁、不 kill 未识别进程、不继续 DDL。
- repair 工具可使用 migrator identity，但只能接受 revision/operation allowlist 和明确数据库 identity，不能演化成任意
  SQL、任意路径或远程管理接口。

### [ADR-0067-C04] 每个 revision 声明可逆性、写入偏差和资源行为

每个非平凡 revision 必须在 migration/module 附近声明并经 review：来源/目标 revision、transaction mode、锁级别、
可能扫描/重写的表、backfill checkpoint、预计 scratch/downtime、兼容元数据变化、客户端/outbox 前置能力、是否联动
图片或恢复材料，以及以下分类之一：

- **reversible**：down migration 不丢事实，且旧 binary 对 expanded schema 仍有已验证读写能力；
- **forward-only**：schema 可以继续前滚，但 down 会丢新字段或语义；应用失败时修新 binary，不自动降库；
- **irreversible**：删除/合并事实、改变金额/时间解释、无法重建旧值、写入新语义或提升最低兼容版本。

未声明按 irreversible 处理。migration 失败后不得靠当前 ORM shape 或重复 `create_all()`“补齐”；只能按已声明的重入、
down、前滚或恢复路径处理。

### [ADR-0067-C05] schema 和跨端协议遵循 expand → migrate → capability gate → contract

- **Expand** 先增加新旧 backend/客户端均能安全处理的 nullable/default shape 或双读能力；不能在同一发布先删旧列再
  要求所有长期离线客户端“同时升级”。
- **Migrate** 的 backfill 必须有稳定批次/游标、幂等写、进度、失败边界和财务/引用校验；重启后能判断最后已提交批次。
- **Capability gate** 必须证明所有允许写入的 backend、最低支持客户端、Web contract 和仍可 replay 的 outbox payload
  都能生产/解释新语义。User-Agent、安装版本名或“同 release 发出”不是证据。
- **Contract** 才允许收紧 NOT NULL/CHECK、删除旧列/parser 或提升 `schema_min_compatible`。旧 writer/outbox 在 contract
  后必须得到稳定 `upgrade_required`/显式 conflict，不能被默认值反序列化后写错。
- 当前不支持两个 backend 版本同时 active。新 schema + 旧 binary、旧 schema + 新 binary、N backend + N-1 client、
  N client + N-1 backend 和长期离线重连都必须进入 release matrix；只测最新组合不能通过 contract gate。

### [ADR-0067-C06] pre-DDL recovery point 必须可验证且绑定本次 plan

- 对 managed/待 adoption 的已有库，在第一次 DDL、backfill、compatibility metadata 写入或 seed 前，writer 已冻结的
  PostgreSQL snapshot 必须成功产生。默认使用受保护的 custom-format `pg_dump`；仅“文件存在”不算成功。
- manifest 至少绑定 source database identity、from revision/compatibility、target revision、backend/release identity、
  UTC 时间、dump hash/size、`pg_restore --list` 结果、创建主体和本次 lifecycle receipt。
- unattended 安装/升级不允许用环境布尔值静默跳过。若 owner 已提供外部恢复点，豁免必须验证同一 database identity、
  记录 risk owner/期限/理由并生成等价 receipt；无法验证则不迁移。
- migration 若改变图片引用、删除状态或其他跨存储关系，恢复点必须同时绑定同一 writer barrier 下的 uploads manifest/
  snapshot；单独 DB dump 不能证明图片可恢复。纯 DB schema change 应显式声明 asset N/A。
- backup 失败、目标目录越界、空间不足、hash/list 校验失败时停在 `REFUSED`，数据库仍保持 inspect 前 shape。

### [ADR-0067-C07] no-return point、应用回退和数据库恢复分开裁决

- irreversible revision 在执行破坏性语句前必须记录 no-return point，并证明 backup restore drill、验证查询、owner/risk
  acceptance 和前滚方案已就绪；`schema_min_compatible` 的提升与第一个不兼容事实处于同一受控提交边界。
- `READY` 前 writer 始终冻结，所以失败时恢复 pre-DDL snapshot 不应丢失外部已接受写入。若出现写入，说明隔离契约
  已失败，必须作为数据事故处理，不能静默 restore。
- schema 仍是 expanded-compatible 且未跨 no-return 时，旧 application binary 只有在 N-1 matrix 明确通过后才可回退；
  “旧 EXE 能启动”不是兼容证明，也不得顺手执行 down migration。
- 跨 no-return 后优先前滚修复。整库恢复必须在隔离的新 database 上 `pg_restore`，校验 schema、identity、逐账本
  财务汇总、关键引用和配套图片 manifest，再在 writer 冻结状态下切换；禁止直接覆盖 live database。
- `READY` 后一旦接受了仅新 schema 可表达的事实，恢复旧 snapshot 会丢写入。此时必须先导出/对账并由 owner 明确
  接受损失或执行可证明的反向迁移；安装器不能自动把旧程序指向新库或把旧 dump 覆盖新事实后报告成功。

### [ADR-0067-C08] seed 是 schema 后置、幂等且非权威迁移的操作

- seed 只创建缺失的系统默认/初始记录，必须可重复执行并按原子单位提交；不能修改已有用户财务事实、猜 legacy
  tenant、做大规模 backfill、创建/修改表或替 Alembic 写 compatibility metadata。
- 历史数据规范化、约束修复和 identity adoption 都属于显式 migration，必须享有同样 backup/no-return/验证边界。
- seed 失败时 schema 可以已在 target head，但服务保持 `REPAIR_REQUIRED`/not-ready；重启只能重试幂等 seed，不得
  自动 downgrade。只有 seed 和 post-migration checks 全部通过才创建 runtime pool 并启动后台任务。
- post-check 至少验证单一 Alembic head、semantic compatibility、关键 CHECK/FK/UNIQUE、migration 声明的行数/金额/引用
  对账、runtime role 无 DDL 权限，以及没有未完成 migration receipt。

### [ADR-0067-C09] 失败矩阵决定副作用、重试和用户动作

| 失败点 | 已允许副作用 | 系统状态 | 安全重试/处置 |
| --- | --- | --- | --- |
| DB 不可达、lease/宿主锁竞争 | 无业务/schema 写入 | `REFUSED` | 有界重连；确认旧进程/锁 owner，不得抢锁 |
| inspect/compatibility 失败、DB 更新或 lineage 未知 | 只读查询 | `REFUSED` | 安装正确 binary 或进入显式 adoption/repair；禁止 seed/create_all |
| backup/manifest/空间检查失败 | 备份临时文件可隔离清理；DB 未变 | `REFUSED` | 修复空间/权限/工具后从 inspect 重跑 |
| 事务内 migration 失败 | 当前 transaction 回滚 | `REPAIR_REQUIRED`，先验证原 revision | 确认 revision/约束未变后可按同一 plan 重试 |
| 非事务 backfill/index 中断 | 仅已提交 checkpoint | `REPAIR_REQUIRED` | 由 revision 的 checkpoint/repair 继续或前滚；不得开放旧 writer |
| irreversible step 后失败 | schema/事实可能已改变 | `REPAIR_REQUIRED` | 优先前滚；必要时隔离 restore 并验证，禁止普通应用回退 |
| post-check 失败 | target revision 可能已提交 | `REPAIR_REQUIRED` | 保留证据，修 migration/数据或恢复；不靠改 marker 变绿 |
| seed 失败 | schema 已验证，seed 原子单元可能部分完成 | `REPAIR_REQUIRED` | 幂等重试 seed；不重复财务副作用、不 downgrade |
| readiness 发布/进程崩溃 | 以 lifecycle receipt 判断是否已开放 writer | `REPAIR_REQUIRED` 或重新验证 | 不从端口/PID 猜状态；重新取得 lease 后从 inspect 验证 |

所有面向 owner 的失败必须说明：当前 revision、是否执行过 DDL、恢复点是否有效、是否可安全重试、是否已越过
no-return、数据是否仍在以及唯一允许的下一步。客户端在维护窗口保留 outbox，不得因 backend 不可达清空未提交意图。

### [ADR-0067-C10] 可观测性和回执不得泄露业务数据或伪造权威

- 结构化事件至少覆盖 lock、inspect/classification、backup、revision start/commit/fail、checkpoint、no-return、post-check、
  seed、readiness 和 recovery；字段包含 lifecycle/plan ID、数据库 identity 摘要、from/to revision、步骤、耗时、结果和
  repair code。
- 禁止记录 DATABASE_URL、密码、token、SQL 参数、账单明文、图片路径或 dump 内容。数据库 identity 使用不可逆摘要，
  能关联同次 ceremony 但不能反推出凭证/主机秘密。
- PG 内 migration audit、host-side lifecycle receipt 和 release evidence 相互校验；任何一个都只是状态证据，不是 schema
  权威。receipt 必须能区分 never-started、pre-DDL-failed、rolled-back、target-committed、ready 和 repair-required。
- 运行指标至少记录无迁移启动开销、锁等待、backup/restore duration、各 revision duration/rows、失败 phase 和
  repair-required 次数；超过预算触发人工维护，不通过关闭 backup/validation 降级。

### [ADR-0067-C11] 容量、锁等待、停机和背压有可测预算

- 在发布所记录的基准 Windows/PG 环境及参考数据集（100,000 笔 expense、1,000,000 条 item/fact、数据库不超过
  5 GiB）上，无 pending revision 的 lifecycle 检查新增 p95 启动耗时不得超过 3 秒；测量不含 PostgreSQL 本身启动等待。
- migration lock 等待上限默认 30 秒。升级默认 owner maintenance window 为 20 分钟；若 plan 的最近实测/估算超过
  窗口，unattended upgrade 必须在 pre-DDL 阶段拒绝，并转入有进度和取消边界的人工维护流程。
- preflight 要求 `free_bytes >= estimated_dump_bytes + declared_scratch_bytes + 20% headroom`；没有可靠估算时两项都按
  `pg_database_size` 计。空间不足不得尝试“先迁移再备份”。
- 任何超过 30 秒的 backup/backfill/index 必须至少每 30 秒发不含业务内容的 heartbeat/progress；无界全表扫描、无
  statement/lock timeout 或不可中断外部进程不能进入 unattended path。
- migration 期间对外保持明确 maintenance/not-ready；不排队到 backend 内存。客户端可持久保留本地 intent 并退避，
  但不得在恢复后绕过 payload version、OCC 和 idempotency gate 集中冲击数据库。

### [ADR-0067-C12] 宿主可以替换，迁移协议和单 writer 前提不能被绕过

Windows adapter 负责 SCM stop/process identity、机器锁、凭证注入和 lifecycle receipt；Linux/service manager、容器或
云端 adapter 可以替换这些机制，但必须实现同一状态、writer barrier、migrator/runtime 分权、恢复点和验证结果。
固定路径、注册表、PowerShell、Inno、端口或 GUI 不进入 migration plan/domain type。

未来多机器或 rolling deployment 必须先由新 ADR 增加共享 fencing、migration ownership、backend version skew、
长任务 claim 和连接 draining，并证明旧 writer 无法在 contract migration 后继续提交；在此之前检测到多个 active
writer/未知 session 必须 fail closed。不能因 PostgreSQL 本身支持并发，就把 schema migration 当普通并发请求。

## [ADR-0067-CONSEQUENCES] Consequences

- **Good**：不兼容 binary、未知 lineage、备份失败和锁竞争都在第一条 DDL 之前停止；Alembic 不再被当前 ORM shape
  绕过，应用/数据库回退和整库恢复有明确边界。
- **Good**：schema owner 不再是长期公网 backend 身份；宿主适配可替换而不重写账本权威或 mixed-version 语义。
- **Good**：离线客户端和旧 outbox 成为 contract migration 的正式前置条件，不能用同步发布假设吞掉。
- **Costs**：需要重构启动顺序、补 fresh-DB Alembic baseline、独立 migrator/runtime credential、migration manifest、
  host receipt、PG integration matrix 和真实 restore drill；首装/升级会多一次可见 preflight。
- **Costs**：部分原本能自动“修好”的 pre-Alembic/漂移数据库会进入 repair，需要明确 adoption 工具和维护者介入。
- **Limits**：当前仍是停机升级、单 active writer；本 ADR 不承诺 rolling migration 或零停机。20 分钟预算是默认家庭
  自托管 envelope，不是不可调整的领域常量；超过它必须显式维护 ceremony 和新测量，不能静默等待。
- **Residual risk**：`pg_dump` 是逻辑恢复点，不保证 PostgreSQL 主机、图片 bytes、恢复密钥或安装配置完整；涉及这些
  对象时必须组合各自 authority/recovery manifest。风险由 owner 接受，任何跨存储 migration 前重新评审。

## [ADR-0067-REVERSIBILITY] Reversibility, Replacement and Retirement

本协议的实现可迁移但代价中高：可把 in-process coordinator 替换成独立 migrator、把 `pg_dump` 替换成经验证的物理
snapshot，或在规模触发后改成 shadow database/blue-green；替换前必须双跑 classification、revision plan、恢复验证和
receipt，并证明失败状态不被弱化。

“先 compatibility/backup，后 mutation”“单 migration owner”“旧 binary 对未知 schema fail closed”和“恢复先在隔离库
验证”不可直接放宽。若 5 GiB/20 分钟 envelope 连续超限、停机窗口不可接受、多个 active writer 成为真实需求，或逻辑
dump 的 RTO/RPO 无法满足 owner 需求，应新 ADR 选择物理 snapshot、online expand/backfill 或 blue-green，并迁移本 ADR
的 no-return/证据语义后 supersede。

[[0031]] 的 SQLite shadow/cut-over、文件 rename 和 30 天 file rollback 不再复活；其历史正文保留。退役当前
`create_all/stamp inference` 桥之前，先提供 Alembic fresh bootstrap 和已知 legacy adoption path；不能直接删除后让已有
数据库失去入口。

## [ADR-0067-EVIDENCE] Verification and Evidence

**当前失败证据（2026-07-11 代码审查）**：

- `backend/app/database/__init__.py::init_db` 在任何 compatibility/backup 前执行 `Base.metadata.create_all()`，随后写
  baseline marker、推断/stamp Alembic、seed identity/runtime；直接违反 C01/C02/C08。
- `backend/app/database/__init__.py::_stamp_alembic_baseline_if_needed` 在当前 ORM 已改库后按列存在推断 revision；真实
  pre-Alembic 数据库无 version table 时跳过 pre-upgrade backup；违反 C01/C06。
- `backend/app/main.py::lifespan` 先 `init_db()`、后 `assert_binary_compatible_with_db()`；旧 binary 或 schema drift 可能先
  发生 DDL/seed；违反 C02/C05。
- `backend/app/database/__init__.py::_warn_if_default_database_url` 对 production superuser/owner credential 只 WARN，
  当前没有 migrator/runtime 分权和 database-wide migration lock；违反 C03。

因此本 ADR 虽已 accepted，当前实现必须保持 `nonconformant`，最新验证保持 `failed`；以上路径修复并形成真实 receipt
之前不得用文档、marker 或局部 unit test 改绿。

目标证明至少包括：

- C01/C02/C08（`data-high`）：fresh DB 仅由 `alembic upgrade head` 建立；managed、newer、unknown、empty fixtures 的
  read-only classification；backup 失败前后 catalog diff 为零；seed 重试不改变已有财务事实。
- C03（`data-high` + security negative）：两个 migrator 并发仅一方取得 lock；未知 writer 阻断；runtime role 的
  ALTER/CREATE/DROP 由 PostgreSQL 拒绝；日志/SCM/HTTP 上下文无 migrator secret。
- C04/C05（`data-high`）：每类 revision 的 upgrade/downgrade/interrupt fixture；N/N-1 backend/client、unknown enum、
  长离线 outbox 和 contract gate matrix；旧 payload 不被默认值执行。
- C06/C07/C09（`recovery-high`）：backup tool/磁盘/进程崩溃/非事务 DDL/seed/readiness 故障注入；custom dump 在隔离库
  restore 后通过 revision、identity、逐账本金额/引用和 asset manifest 校验；no-return 后旧 binary 稳定拒绝。
- C10/C11（`runtime`）：receipt 状态转移、敏感字段反向测试、5 GiB reference workload 的 p95/20 分钟/空间/heartbeat
  测量；超预算在 pre-DDL 阶段失败。
- C12（`deploy-critical`）：Windows clean-machine upgrade/repair 和至少一个非 SCM harness 使用同一 migration contract；
  检测多 writer 时不得开始 DDL。

反向验收：出现任一情况即证明契约尚未成立——runtime 启动调用 `create_all`；compatibility check 晚于任何 DDL/DML；
有业务数据的库无有效 recovery point 仍迁移；旧 binary 对更高 min-compatible schema 开放写入；两个 migrator 或旧 writer
与 migration 并行；seed 修改历史财务事实；恢复直接覆盖 live DB；安装器只因 `/health=200` 就报告 schema 升级成功。

## [ADR-0067-REFERENCES] References

- [[0031]]：已退役 SQLite cut-over 历史；当前 PostgreSQL 生命周期由本 ADR supersede。
- [[0041]]：PostgreSQL-only、row_version 与 DB 约束方向继续有效，本 ADR收紧 schema lifecycle。
- [[0062]]：Windows 宿主安装/升级锁、回执和 repair 边界。
- [[0066]]：家庭账务事实系统及安装升级/恢复承重域。
- [跨端协议、mixed-version 与 schema 演进契约](../architecture/PROTOCOL_EVOLUTION.md)
- [全系统权威源登记表](../architecture/AUTHORITY_SOURCE_REGISTER.md)
- [PostgreSQL — Advisory Locks](https://www.postgresql.org/docs/current/explicit-locking.html#ADVISORY-LOCKS)
- [PostgreSQL — SQL Dump / pg_dump and pg_restore](https://www.postgresql.org/docs/current/backup-dump.html)
- [Alembic — Cookbook](https://alembic.sqlalchemy.org/en/latest/cookbook.html)
