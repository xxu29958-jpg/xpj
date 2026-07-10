# ADR 实质架构契约审查（2026-07-11）

本审查不是 ADR、不是机器权威，也不以“文档格式通过”替代架构判断。它记录每份现行 ADR 相对真实代码、
运行拓扑和冻结产品边界的审查证据，并给出明确处置。方向改变由后续 `supersedes` / `amends` / `refines`
ADR 承担；历史正文不批量改写。

## 审查基线与证据边界

- 产品基线：小票夹是**本地优先的家庭账务事实系统**，不是早期“小票上传工具”。
- 承重域：宿主机生命周期、账本权威、家庭身份、多端写入、离线冲突、财务事实、图片与 AI 建议、
  安装升级与数据恢复。
- 主线代码：`0f1092e625b376d0fa8d4abc214cdc53de93a96d`。
- 安装器 overlay：`codex/release-hardening-installer-lifecycle` 工作树；其未提交代码只证明当前实现方向，
  **不等于主线已实现、发布已验证或可恢复性已经成立**。
- 裁决顺序：数据库约束/领域服务/协议实现 > 自动测试 > 当前运行拓扑 > 现行 ADR > 历史路线图和旧产品叙述。
- “实现存在”与“契约成立”分开：源码关联只能证明 linked；高风险条款还需数据库、并发/故障测试、
  安装实机或恢复演练。

处置词义：**保留**表示决定本体仍正确；**收紧**补上安全或失败边界；**放宽**移除误冻的实现细节；
**拆分**表示一份 ADR 混合多个独立决定；**修订**由 amendment/refinement 更新当前适用部分；
**废弃**表示不再裁决当前系统；**supersede** 表示由新决定取代。代码违反仍正确决定时标
`nonconformant`，不得通过降低 ADR 要求消除红灯。

## 当前产品边界裁决

以下边界优先于早期上传器叙述：

1. PostgreSQL 是结构化账务事实、权限、状态机和引用关系的唯一在线权威；客户端缓存不能反写成为真源。
2. 收据图片是独立受保护的二进制证据；PG 引用不能凭空重建 bytes，数据库备份成功不等于图片可恢复。
3. OCR/AI 只产生可追踪建议；只有经授权的人工确认/明确命令才能改变权威财务事实。
4. Account、Ledger、LedgerMember、Device、AuthToken、UploadLink、Web session、维护凭证和恢复材料是不同
   权限域；owner、member、维护者和恢复主体不能合并成“管理员”。
5. Android Room confirmed 数据是可丢弃投影；设备尚未提交的 outbox intent 是该设备本地持久事实，
   但不是账本事实。清缓存与丢弃未提交意图是两种完全不同的操作。
6. Windows 是当前宿主 adapter；SCM、注册表、PowerShell、Inno、固定路径和 loopback 不能进入领域核心。
7. 单机单 active writer 是当前部署条件，不是领域永久前提；未来 Linux/云端/多机器增加 adapter 和协议门，
   不能要求重写金额、账本、身份或人工确认核心。

## Release / Merge 阻断项

| ID | 证据与失败语义 | 影响 | 明确处置 |
| --- | --- | --- | --- |
| AUD-P0-DB-001 | `backend/app/database/__init__.py` 在既有库上先 `Base.metadata.create_all()`，之后才做备份/Alembic；`backend/app/main.py` 又在初始化后检查 binary/schema compatibility。 | 迁移前恢复点和旧 binary fail-closed 均不成立；失败可能留下无法证明的混合 schema。 | 新 schema lifecycle ADR supersede [[0031]] 的当前权威并 refine [[0041]]；实现顺序改为 inspect → compatibility → backup → Alembic → seed。修复前为 Release Blocker。 |
| AUD-P0-OFFLINE-001 | `android/.../AppDatabase.kt` 的 10→11 migration drop/recreate `pending_mutations`；`ExpenseRepositoryCore.kt` / `OutboxRepository.kt` 在 logout 或换绑时可全局 `clearAll()`，没有未同步数、Sync/Discard/Cancel 或最后锁内复核。 | 升级、退出或换账本会静默丢用户离线意图；这不是“清可重建缓存”。 | 新 offline-intent/binding-exit ADR refine [[0038]]/[[0042]]；旧 row 进入 quarantine，退出按 binding scope 显式决策。修复前为 Release Blocker。 |
| AUD-P0-OFFLINE-SEND-001 | `ExpenseDetailRepository.kt` 在本地持久化 intent/key 前先直发网络，只在 `IOException` 后 enqueue。 | 发送与落盘之间 crash/断电会丢唯一 key；服务端 committed-but-unseen 后用户重试可生成重复财务事实。 | [[0069]] 收紧为 write-ahead intent：先原子持久化，再由统一 dispatcher 发送；补 commit-response 丢失和进程 kill 测试。修复前为 Release Blocker。 |
| AUD-P0-IDEMP-001 | `backend/app/models/idempotency.py` 未保存首次响应 envelope/principal/device；`services/idempotency.py` 允许 10 分钟 stale reclaim，并在 HIT 时重新序列化当前资源。 | committed-but-unseen 可能二次执行；同 key 得到不同结果；不同主体可碰撞同 tenant key。 | [[0057]] 决定本体保留，状态改 `nonconformant/failed`；实现稳定首次结果、principal/device binding、无 reclaim、sweep 与 PG 并发故障测试。 |
| AUD-P0-CURRENCY-001 | home currency 只来自 env/default；Android/Web/CSV 多处固定 `/100` 或未知币种回落 CNY；握手无 currency contract revision。 | 修改配置可重解释历史整数，JPY 等币种可能数量级错误，旧客户端可继续错误写入。 | [[0061]] 保留并标 `nonconformant/failed`；在完整 binding/capability 前对非 CNY fail closed。 |
| AUD-P0-AUTHZ-001 | [[0022]] 仍描述旧权限矩阵和 `/web` loopback；当前 `permission_service.py`、owner transfer、Web session、UploadLink 管理面已改变。`ALLOW_PUBLIC_ADMIN_API` 还能扩大 `/api/admin` 公网面。 | 旧 ADR 会授权错误主体、错误入口和错误信任边界。 | 新家庭 RBAC/trust-boundary ADR supersede [[0022]]，tighten [[0028]]；未经独立决定不得公开 admin surface。 |
| AUD-P0-RECOVERY-001 | 主线备份路径仍可能把数据库 URL 放 argv，offsite 归档未加密且 DB dump 不能恢复 uploads；installer overlay 已改用短命 `PGPASSWORD` 子进程环境并隔离 bootstrap handoff，但还不是同代 DB+bytes+identity 恢复证明。 | “有备份”可能同时造成隐私外泄和不可恢复；旧 bearer/clone 身份可能复活。 | tighten [[0059]] 和 installer recovery contract；长期目标用 SYSTEM/Admin-only 临时 `PGPASSFILE`，云副本默认关闭或用户密钥加密，DB+uploads+identity 做同代恢复演练。 |
| AUD-P0-INSTALL-001 | installer overlay 在 Inno `[Files]` 复制开始时只设置进程内 `LifecycleFilesMayBeReplaced`，持久 receipt 要到复制后 service script 才从 `prepared` 转为 `files_may_have_been_replaced`。当前 retry **不会**把 stale `prepared` 当 pre-copy：`prepare_bundled_upgrade.ps1` 只信 `captured` 为 pre-copy，其余阶段均保守进入 files-may-have-been-replaced repair。 | 当前保守分支避免了已知 retry 的危险恢复，但 receipt 本身仍不能证明断电发生在复制边界哪侧；其他/未来消费者若只按持久阶段裁决会误判，且无 durable atomic no-return 证据可供审计或故障恢复证明。 | [[0062]] 保持 `nonconformant/failed` 与 Release Blocker；在第一字节可能覆盖前持久化 copy-boundary/no-return point，marker 使用 durable atomic protected writer，并做 kill/power-loss/repair 故障注入。 |
| AUD-P0-ASSET-COMMIT-001 | `expense_service/_create.py` 在异常/finally 路径删除新建 source/thumbnail，未区分确定 rollback 与 COMMIT outcome unknown。 | COMMIT 已落库但 ACK/连接丢失时，补偿可删除权威 PG 引用的唯一 bytes，留下永久缺图。 | [[0071]] C03 收紧：预分配 asset/idempotency identity；只有证明未提交才删，unknown outcome 从新连接回查，否则 quarantine/reconcile。修复前为 Release Blocker。 |
| AUD-P1-OWNER-001 | `Ledger.owner_account_id` 与 active `LedgerMember(role=owner)` 同时表达 owner，数据库未强制唯一 active owner；配对、管理和 transfer 路径读取不同表示。 | 不一致时不同入口会授权不同家庭主体，restore/repair 也无法知道信谁。 | [[0068]] 选定 active `LedgerMember(role=owner)` 为 canonical owner/capability source；`owner_account_id` 只作受约束兼容投影，以 DB constraint、transfer transaction 和 repair 强制一致并最终退役。 |
| AUD-P1-RECOVERY-REENROLL-001 | [[0059]] 要求 restore 撤销备份内全部 active bearer/one-shot；但 `Account` 无密码登录，正常 pairing 需要有效 owner app context，loopback Owner Console 仍以“第一个 Account”隐式选 owner且正被 [[0068]] 退役。当前没有独立于可回滚数据库凭证的恢复主体。 | 安全 sanitation 后 owner 可能永久失去签发新 session/device 的合法入口，迫使系统保留旧 bearer 或重新开放隐式本机 owner，二者都会破坏恢复安全。 | [[0059]]/[[0068]] 收紧：引入不随 DB generation 回滚、绑定 installation/recovery epoch 的 sealed recovery principal；它只能为 canonical owner 签发一次短 TTL re-enrollment，缺失或 invariant 失败时 listener 保持关闭并进入显式 adoption。 |
| AUD-P1-HANDOFF-ACL-001 | installer overlay 把 `owner-bootstrap.txt`、`owner-handoff-pending` 和 recovery marker 放在 `DataRoot\app`，同时给 backend 虚拟账户对该父目录可继承 FullControl。子文件 SYSTEM/Admin-only ACL 阻止读取，却不能收回父目录的 `DELETE_CHILD`/create/rename；backend 又在 Inno 读取 handoff 前重启。 | 失陷或错误 backend 可删除/替换交付路径和恢复 marker，造成 owner 凭证不可见、恢复状态伪造或 repair DoS；“服务账户读不到明文”不足以证明隔离。 | [[0063]]/[[0068]] 标 failed：把 handoff、receipt、recovery marker 移到生命周期锁同级的 SYSTEM/Admin-only sibling，父目录不授 backend write/delete；用真实 `NT SERVICE\<backend>` token 做 read/delete/rename/replacement 负测。 |
| AUD-P1-MONEY-001 | 多数金额列是 PostgreSQL 32-bit `Integer`，部分 parser 却允许远高于 2,147,483,647 minor units；Web/AI 路径还有默认 half-even 或 float/round。 | 极端金额会 DB overflow 或跨端取整不一致，不能只靠“没有 float 列”宣称金额契约成立。 | [[0073]] 统一 signed 64-bit carrier、领域上限和 ROUND_HALF_UP；逐列 expand/backfill/contract，并做边界/聚合溢出测试。 |
| AUD-P1-CURRENCY-SCOPE-001 | [[0061]] 已决定当前 home currency 是 installation-global，但 [[0069]]/不变量目录曾写成 ledger-scoped；[[0073]] 又沿用 installation-global。 | 两个 accepted 方向会让客户端 envelope、迁移和跨账本汇总选择不同权威。 | 本切片以 [[0061]] 为准，统一为 `installation_currency_binding_revision`；未来 per-ledger 必须 successor + 事实/旧 intent/跨账本投影迁移，不得暗改。 |
| AUD-P1-TIME-PRECISION-001 | [[0070]] 允许 date-only/不确定时刻并禁止伪造 instant；[[0073]] 曾要求所有确认冻结 event instant。 | 历史导入会被迫制造虚假 UTC/中午，排序、FX 日期和审计语义失真。 | [[0073]] 改为冻结带 precision/source-zone provenance 的 event-time representation；只有时刻已知时才要求 offset-aware instant。 |
| AUD-P1-PROJECTION-001 | bill-split/invitation 接受可同时创建 receiver Expense 与 Debt，而当前支出聚合只按 confirmed Expense；旧 [[0029]] 的家庭总览 double-count 风险未被 successor 承接。 | 将来跨账本家庭合并可能把同一购买、负债和还款重复计入支出或现金流。 | [[0073]] 增加事实类型→ledger/household/cash/liability/gross-net 投影矩阵与 household economic-event identity；缺 double-count golden test 的新类型不进投影。 |
| AUD-P1-AI-EGRESS-001 | 收据/债务图像会完整发送给 local-loopback vision provider；Budget Advisor 另有结构化 allowlist，但旧 ADR 未明确两者不能互相授权。 | 目录若自行宣布 provider 隐私边界，会越权成为决策源；未来换远程 vision 可能静默外发家庭原图。 | [[0073]] C08 收紧：原图当前 local-loopback-only；远程原图 provider 必须独立 accepted privacy/security 决策、用户知情和逐 provider egress/retention/revoke 契约。 |

## 逐份 ADR 裁决

### 0001–0014：基础事实、客户端与早期上传路径

| ADR | 承重域 | 代码证据与影响 | 处置 |
| --- | --- | --- | --- |
| [[0001]] 金额整数 | 账本权威、财务事实 | 权威金额没有 float、FX 使用 Decimal；但多数列仍是 32-bit Integer，部分 parser 上限超出 DB，标题“分”也不适用于 JPY/KRW。 | **保留并收紧**为“有界 signed 64-bit minor unit + 显式 currency/rounding”；[[0061]]/[[0073]] refine。退款使用 linked reversal fact。 |
| [[0002]] 消费时间 | 财务事实、多端写入 | `spending_contract_service.stat_time_expr()` 已用 `expense_time → confirmed_at`；但 naive 输入在手工/CSV/OCR 路径被解释成不同 zone，账务时区不是持久 binding。 | **supersede 当前适用范围**：新 accounting-calendar ADR 定义 aware-only、accounting date、DST、设备错钟和迁移；保留历史事实/创建时间分离原则。 |
| [[0003]] uploads 不公开 | 图片/AI、账本权威、恢复 | 原图经租户鉴权 API 读取且非静态目录；响应仍暴露内部 path/hash，读取不重验 hash，DB 引用与 bytes 缺失无完整恢复协议。 | **保留并收紧**访问边界；另立 binary-asset authority/recovery ADR。内部路径逐步从公共 DTO 移除。 |
| [[0004]] auth check 非 health | 家庭身份、多端写入 | Android `AuthApi.checkAuth()` 和连接仓储不会把 health 当身份；预检也先区分可达与鉴权。 | **保留并放宽路径细节**：长期契约是 authenticated identity/capability check，不永久冻结 `/api/auth/check` URL。 |
| [[0005]] Room ledger/server identity | 账本权威、多端写入、离线冲突 | `ExpenseEntity` 及 DAO 以 ledger scope + server/public/client identity + rowVersion upsert；outbox/OCC 已超出原决定。 | **保留并收窄**到可重建缓存身份；[[0042]] 接管 intent、OCC 与 committed-but-unseen。 |
| [[0006]] PowerShell BOM | 宿主生命周期、安装恢复 | 编码脚本和 CI 守卫 Windows PowerShell 5.1 BOM/CRLF。 | **保留但限定 Windows adapter**；Linux/容器/领域代码不继承。 |
| [[0007]] 实机预检 | 宿主、身份、多端、图片/AI | 脚本仍冻结 iPhone→Windows→Android debug 拓扑，并允许 token 通过 CLI/process env；残留 pending 清理没有持久幂等记录。 | **废弃为 ADR**，迁为版本化 E2E profile/runbook；凭证改安全输入/ACL 临时文件 + TTL，清理结果可观测。 |
| [[0008]] UUID + theme JSON | 账本权威、多端写入 | public ID 已扩到多资源；主题实际由 Android DataStore/本机资源管理，不是 JSON 业务权威。 | **拆分**：公共资源身份进入协议 ADR；主题只保留 local-only 客户端配置，不与业务身份共用决定。 |
| [[0009]] Version Catalog | 供应链、安装恢复 | 依赖大体由 catalog 管理，但 `android/app/build.gradle.kts` 仍硬编码 serialization force；项目已有经批准 alpha 例外。 | **收紧并标 partial/nonconformant**；constraints 也进 catalog，预发布用限时例外与退出条件，删除“永不预发布”绝对句。 |
| [[0010]] 依赖版本审计 | 供应链 | `check_dependency_versions.ps1` 默认只报新版；它不证明许可证、漏洞、来源、hash 或构建可追溯。 | **修订**：freshness advisory 与确定性 release gate 分开；联网结果不得作为唯一可重复证据。 |
| [[0011]] Android 工具链升级 | 供应链 | 固定版本仍匹配当前 catalog，但它是一次升级快照；“无 alpha”已被 [[0050]] 有条件反转。 | **废弃为 informational 历史**；版本与例外由依赖注册表/新决定裁决。 |
| [[0012]] UI 错误与诊断 | 多端写入、交互、观测 | `ErrorUiText.kt` / `NetworkErrorHandler.kt` 仍可能把 `Throwable.message` 给用户；图片 debug 日志可能记录响应 body。 | **修订并收紧**：未知错误用稳定 copy；诊断 allowlist/脱敏；写失败必须说明副作用、outbox、重试安全和冲突。 |
| [[0013]] 分类目录 | 财务事实、账本权威 | 后端默认目录、账本自定义分类和 Android alias 并存，说明它不是封闭 enum；双端常量可能漂移。 | **保留并收紧** catalog/version、旧客户端兼容、alias 迁移与退役规则。 |
| [[0014]] iOS raw file body | 多端写入、图片/AI | 后端受限 raw body 与 multipart 都支持；iOS 版本、UA 和 Cloudflare 1010 是历史环境经验。 | **废弃为架构决定**，迁 iOS Shortcut runbook；UploadLink、限额、流式校验由身份/上传协议承担。 |

### 0015–0031：建议管线、家庭权限、公共 Web 与迁移

| ADR | 承重域 | 代码证据与影响 | 处置 |
| --- | --- | --- | --- |
| [[0015]] OCR pipeline | 图片/AI、财务事实、多端写入 | provider/parse/draft 分层、失败不阻断上传、只写 pending 均成立；`OcrFact` 已替代旧 raw_text 叙述，同票 enrichment 尚无单飞。 | **修订** provenance/version、provider egress、背压和失败可见性；保留“自动化只建议”。 |
| [[0016]] 性能稳定基线 | 横切八域 | 仍冻结 SQLite、无后台任务框架；当前是 PostgreSQL、后台任务、Room/web 多投影。分页、聚合、cache 等局部原则仍有价值。 | **由 PG capacity/backpressure/task ADR supersede**；旧拓扑条款废弃，局部性能原则迁入 successor。 |
| [[0017]] 灰度产品边界 | 家庭身份、交互 | 当前已有家庭账本、债务、预算、邀请、owner transfer、公开 Web session；Basic UI 也会展示 server 地址。早期上传器范围不再能裁决。 | **由“家庭账务事实系统边界”ADR supersede**；保留敏感凭证不暴露和角色分面原则。 |
| [[0018]] withdrawn | 无 | 编号 tombstone，无实现消费者。 | **保留 rejected tombstone**；不得复用编号或产生实现债。 |
| [[0019]] 本机背景 | 客户端隐私 | Photo Picker→私有目录→DataStore 成立；copy 无明确大小/格式上限，固定 JPEG/9:16 是实现细节。 | **放宽**固定实现，保留 local-only/不上传；补资源上限与异常 ContentProvider 测试。 |
| [[0020]] 支付宝 OCR 规则 | 图片/AI、财务事实 | parser 已演进成多 profile 候选评分；ADR 固定商家词和权重会阻碍算法演进，也缺 parser version。 | **拆分**：保留可解释候选+置信度+人工确认；权重/词表进入版本化算法 registry 与 golden corpus。 |
| [[0021]] OCR 字段来源 | 图片/AI、财务事实 | `ocr_draft_fields` 与用户 PATCH 清除 ownership 已实现；永久 5 分钟 legacy heuristic 和 SQLite 迁移叙述已失效。 | **修订** per-field ownership/fact version 与 heuristic 退役触发；[[0037]] refine。 |
| [[0022]] 家庭权限 | 家庭身份、账本权威、多端写入 | 当前权限来自 `permission_service.py`；owner transfer 已实现；member 不能管 UploadLink；`/web` 可公网 session-gated，只有 `/owner` loopback。 | **supersede**：新家庭 RBAC/credential/trust-boundary ADR；当前基线元数据不得继续写 implemented。 |
| [[0023]] 图表政策 | 财务事实只读投影、供应链 | 后端保留结构化统计；Android Canvas/Web ECharts 都只展示，失败不改变账本。 | **保留**；hash/许可证/包体/a11y/失败演练放供应链与验证，不扩写政策。 |
| [[0024]] 三端 UI/UX | 家庭身份、交互 | 跨端同语言不同布局仍合理；`/web` remote 403、普通用户永不见 server 地址均与当前代码冲突。 | **修订**为 member/owner/maintainer 分面，并补 loading/error/partial-side-effect/a11y/极值输入。 |
| [[0025]] Vico | 只读投影 | 代码已移除 Vico，[[0055]] 明确替代。 | **保持 superseded/stale**，不得因不符合旧决定而报 nonconformant。 |
| [[0026]] Web ECharts | 只读投影、身份、供应链 | 自托管 ECharts/fallback/export 成立；local-only 叙述错误，vendor 无机器 SHA-256。 | **修订** browser-session/CSP 边界并固定 digest/升级 gate。 |
| [[0027]] 服务端 FX | 账本权威、多端写入、财务事实 | `exchange_rate_service.py` 用 Decimal、发生日、手工率优先并冻结 snapshot；原 CNY 固定由 [[0061]] 修订。 | **保留并收紧**；客户端不得提交权威 rate，非 CNY 在完整 binding/capability 前 fail closed。 |
| [[0028]] 公共 Web session | 家庭身份、信任边界 | `/web` cookie/Cloudflare Access 与 `/owner` loopback 分离成立；`ALLOW_PUBLIC_ADMIN_API` 却能扩大 `/api/admin`，与“边缘拒绝 admin”冲突。 | **收紧**：默认移除公网 admin escape hatch；若确需开放必须独立 critical ADR、最小权限和故障演练。 |
| [[0029]] 家庭分账隐私 | 家庭身份、财务事实 | invitation accept 当前在同事务创建 Expense、Debt、Claim/Audit；原 ADR 的“只创建 expense、债务解耦”已失效。 | **修订**为单事务 member fact bundle，明确双计数防护、可见性、拒绝/撤销和重试语义。 |
| [[0030]] 长任务模型 | 宿主生命周期、性能、恢复 | 仍以 SQLite/in-process 为永久方案；当前 PostgreSQL task ledger 仍有 enqueue read-then-insert 尾部竞争，云 grace 不是 durable multi-worker queue。 | **由 PG task/executor ADR supersede**；executor 是 adapter，任务事实/幂等/恢复在 PG。 |
| [[0031]] v1 SQLite migration | 安装恢复、历史 | ADR 自身承认 cutover machinery retired；继续作为当前 schema 迁移权威会导致先 DDL、后备份等错误。 | **废弃为 historical**；新 PG/Alembic lifecycle ADR supersede 当前适用部分。 |

### 0035–0049：财务子事实、同步、存储与身份

| ADR | 承重域 | 代码证据与影响 | 处置 |
| --- | --- | --- | --- |
| [[0035]] 行项目折扣/税 | 财务事实 | DB CHECK 与 service recompute 已存在；`items_sum_status` 是可重建投影，不是另一套金额真源。 | **保留并收紧**权威/投影区分、修复与极值金额测试。 |
| [[0036]] AI budget 隐私 | 图片/AI、财务事实 | outbound allowlist fail-closed、建议不写预算成立；SQLite 字样和“所有未来 provider 自动合规”不成立。 | **修订**为 provider-by-provider egress contract；保留人工采纳和聚合最小化。 |
| [[0037]] 学习/OCR facts | 图片/AI、财务事实 | suggestion/event/OcrFact 追加模型成立，但标题“dual tables”已成三类且 append-only 主要靠 service 约定。 | **修订**当前 fact/provenance、retention/PII、DB 不可变证据等级；refine [[0021]]。 |
| [[0038]] 多端同步 | 账本权威、多端写入、离线冲突 | PG/Room/OCC/outbox 基本方向正确；10→11 migration 会丢 pending intent。 | **保留核心并由 offline-intent ADR refine**；当前实现 `nonconformant`，不得把 outbox 当普通 cache。 |
| [[0039]] ADR calibration | 治理历史 | 手工表仍称 [[0016]]/[[0025]] current，并低估 [[0022]] 变化；它不能再当状态权威。 | **保持 superseded/stale**；机器 registry 取代手写状态，但真实实施仍由本审查/证据判断。 |
| [[0040]] outbox target/undo | 多端写入、离线冲突、财务事实 | parent target + CAS anchoring 合理；“undo 只翻 parent 且永久不逆副作用”把不完整补偿误冻为架构。 | **拆分/修订**：保留 aggregate concurrency；用显式 compensation matrix、残余副作用和 rebuild 规则替代通用 undo。 |
| [[0041]] PostgreSQL 迁移 | 宿主、账本权威、恢复 | PG-only、row_version 方向正确；`create_all` 早于 backup/Alembic，compatibility gate 更晚，production superuser 仅 warning。 | **保留 PG/row_version，supersede 生命周期部分**；当前实现 partial/nonconformant，生产 superuser 与不兼容 schema fail closed。 |
| [[0042]] 离线 + 幂等 | 账本权威、多端写入、离线冲突 | FIFO/KeepMine/age cap 大部成立，但 unknown-type 语义漂移、退出清队列、[[0057]] stable result 未成立。 | **修订并标 partial**；offline binding successor 接管退出/quarantine，[[0057]] 接管服务端首次结果。 |
| [[0043]] 标签管理 | 财务事实、多端写入 | rename/delete/merge 领域不变量有效；表名、单事务步骤和旧 SQLite migration 是实现协议。 | **保留并放宽实现细节**；补补偿/ABA/恢复与 mixed-version。 |
| [[0044]] Android strings | 多端交互 | strings.xml 外置方向仍成立，风险低。 | **保留**；无需升格成领域核心或增加沉重证据。 |
| [[0045]] CSRF signing key | 家庭身份、恢复 | 持久随机 key、placeholder 拒绝方向正确；需与 clone/restore identity、Web session 和 bootstrap key 生命周期统一，不能把普通服务账户可读备份当安全恢复。 | **保留并收紧**；[[0059]]/身份 successor refine，恢复后做 effective-secret fingerprint 校验。 |
| [[0046]] recurring 检测源 | 多端写入、交互 | WorkManager 持久周期任务作为检测器合理，具体 timing 不精确；[[0058]] 已补投递语义。 | **保留**并由 [[0058]] refine；不声称 exact time/exactly once。 |
| [[0047]] Windows 服务/安装器 | 宿主、安装恢复 | SCM、虚拟账户、ProgramData、loopback 是 Windows adapter 方向；LAN/mDNS、已入包 manager、精确 ACL/完整升级恢复不能按旧正文一概称实现。 | **保留平台选择并修订状态**；0062–0064 分别接管生命周期、bootstrap、provenance；领域核心不得依赖 SCM/Inno。 |
| [[0048]] Rive | 无 | 已明确放弃且代码无消费者。 | **保持 rejected/stale**，不得复活或制造实现债。 |
| [[0049]] Debt | 家庭身份、账本权威、财务事实 | member/external debt、权限、OCC、repayment/forgiveness 事实已落地；旧 rollout 描述失真，append-only 尚缺 DB 级证明。 | **修订 rollout 与证据等级**；领域决定保留，[[0060]] refine，未来退款不能借 Debt/discount 偷换。 |

### 0050–0065：当前高风险校准、安装恢复与治理

| ADR | 承重域 | 代码证据与影响 | 处置 |
| --- | --- | --- | --- |
| [[0050]] Baseline Profile alpha | 供应链、性能 | 截至审查日官方仍无更新的 1.5 稳定版；例外有明确退出条件。 | **保留限时例外**；稳定版可用即复审，不把 alpha 例外扩散到其他依赖。 |
| [[0051]] 统一回收站 | 财务事实、恢复 | soft-delete/restore 方向成立；回收站是用户恢复功能，不等于隐私删除或备份 purge。 | **收紧** retention、OCC/ABA、备份删除和 owner/member 可见性。 |
| [[0052]] 主数据删除 | 财务事实、恢复 | master/fact 区分和 recycle scope 基本成立；在线 purge 与离线备份/审计保留未统一。 | **收紧**数据擦除与恢复副本语义；不得用 UI“删除”承诺所有备份立即消失。 |
| [[0053]] 商家目录 | 财务事实 | catalog/alias 边界与当前代码一致。 | **保留**；作为可重建/可迁移目录，不提升为金额真源。 |
| [[0054]] 商家 merge | 财务事实、多端写入 | merge/rename 已实现且禁止历史事实重写；没有完整 unmerge，alias 会改变报表归类。 | **收紧可逆性**：执行前明示不可逆/残余影响，或另建可证明的 unmerge；旧 outbox 需显式冲突。 |
| [[0055]] Android Canvas | 只读投影 | 原生 Canvas + design token 已替代 Vico，并有未来库化触发条件。 | **保留**；图表失败不改变账本事实。 |
| [[0056]] ADR 生命周期 | 治理 | 历史不可改写、实施状态分开方向正确；单一状态表仍混合 decision/implementation/verification。 | **由 [[0065]] amend/refine**；保留历史真实性原则。 |
| [[0057]] stable idempotency | 账本权威、身份、多端、离线 | 决定正确，当前 schema/service 明确违反 stable envelope、principal binding 和 no-reclaim。 | **保留决定，状态改 `nonconformant/failed`**；不得另写较弱 ADR 合法化现状。 |
| [[0058]] reminder delivery | 多端交互 | 无 single-flight；one-time/periodic 可重叠；notifier 即使 publish 早退仍报告 SENT。 | **保留决定，状态改 nonconformant**；实现 explicit outcome、Mutex、onlyAlertOnce 与 TOCTOU 测试。非账本 Release Blocker。 |
| [[0059]] secret restore/clone | 家庭身份、安装恢复 | 方向正确；未加密 offsite、DB URL argv、备份/clone sanitation、独立 owner re-enrollment principal 和真实服务账户负测仍缺；overlay 子文件 ACL 还被 backend 父目录 `DELETE_CHILD` 破坏。 | **保留并收紧，状态 nonconformant/failed**；按 signing/bearer/one-shot/operator/recovery 五类治理，同代 restore 撤销回滚能力后只经 sealed recovery principal 重登记 canonical owner，clone 全部换域。 |
| [[0060]] Debt fold | 账本权威、财务事实 | forgiveness 已进 fold；rebuild 仍依赖 mutable `Debt.status` 且排除 `DebtVoid`，无法从 facts 灾难重建。 | **保留决定，状态 partial/nonconformant**；实现纯 fact rebuild、void latch、dry-run/repair 与灾难测试。 |
| [[0061]] home currency | 账本权威、多端、离线、恢复 | 决定正确，env-only binding、固定 `/100`、CNY fallback 和无 capability 直接违反。 | **保留决定，状态 nonconformant/failed**；完整修复前非 CNY fail closed。 |
| [[0062]] installer lifecycle | 宿主、安装恢复 | overlay 已实现四模式、recovery PG toolset、preserved/repair pre-copy dump、机器锁、受保护 receipt 与 post-copy isolation；但 `[Files]` 复制边界先存在于内存，复制后才持久化，marker 写入也不是 durable atomic protected write。主线 `0f1092e` 完全不具备。 | **保留 target；overlay `nonconformant/failed`，main not-started**。在复制前持久 no-return point，做 kill/power-loss/repair 故障注入。 |
| [[0063]] recoverable bootstrap | 家庭身份、安装恢复 | overlay 已有 HMAC、PG advisory lock、listener process proof、same-secret recovery、暴露轮换和 admin-only 子文件 ACL；但恢复会把 UploadLink expiry 重设为 now+TTL，owner ceremony 仍绑死 admin/UploadLink/pairing 一次性交付，且 backend 对父 `app` 目录的 FullControl 仍可删除/替换 handoff/recovery marker。主线没有。 | **保留 target；overlay partial/nonconformant/failed，main not-started**。禁止恢复延寿，拆 owner/recovery 与可选 intake/onboarding；交付/恢复材料迁到 backend 无父目录删除权的 sibling 并做真实服务账户负测。 |
| [[0064]] installer provenance | 安装恢复、供应链 | overlay 已实现 immutable-ish staged source/lock、固定 Python/uv/PyInstaller、staged Inno 输入/read locks、post-build revalidation 和最终 hash/provenance atomic publish；本地 build receipt 存在，GitHub/Gitea real-build workflow 已配置，但没有对应 head 的 cloud run 或 clean Windows VM 证据。仍缺独立上游真实性、签名/时间戳和 clean/tagged release gate；主线没有。 | **保留有限证据语义；overlay partial/unverified，main not-started**。workflow 文本和本地 receipt 只证明关联/候选实现，不得称云 CI、干净实机或端到端供应链已经验证。 |
| [[0065]] executable governance | 治理 | 三状态/clause/ratchet/evidence 工具可固化已确认决定；初版先造工具后做全量实质审查，顺序需要纠正。 | **保留但修订执行顺序**：先完成本审查和 successor 决策，再生成 registry/状态/CI；registry 不是架构真源，工具失败不得篡改业务结论。 |

## 必须新增的最小 successor 集

只为真实冲突或缺失承重契约新增，不为填模板扩张：

1. **[[0066]] 家庭账务事实系统边界**：supersede [[0017]] 的上传器产品范围，明确八承重域与 adapter 边界。
2. **[[0067]] PostgreSQL/Alembic lifecycle**：supersede [[0031]] 当前适用部分，refine [[0041]]；定义 migration/rollback/
   mixed-version/no-return point。
3. **[[0068]] 家庭 RBAC 与信任边界**：supersede [[0022]]，refine [[0028]]/[[0045]]/[[0059]]/[[0063]]。
4. **[[0069]] 离线意图、协议版本与 binding exit**：refine [[0038]]/[[0042]]/[[0057]]；覆盖 Room quarantine、
   Sync/Discard/Cancel、旧客户端与 outbox payload 演进。
5. **[[0070]] 账务时间与 calendar binding**：supersede [[0002]] 当前适用部分；覆盖 accounting date、DST、错钟和迁移。
6. **[[0071]] 二进制收据资产权威与恢复**：refine [[0003]]/[[0059]]；覆盖 DB↔bytes 状态、manifest、备份、恢复和迁移。
7. **[[0072]] PG 容量/后台任务/背压**：supersede [[0016]]/[[0030]] 的旧拓扑；定义 fault domain、queue/executor adapter、
   SLI/SLO 和降级。
8. **[[0073]] 财务事实、更正与投影**：统一更正/reversal、Debt event rebuild、金额宽度/舍入和投影恢复，不做全量 event sourcing。

AI/OCR 不再另造百科全书 ADR：[[0015]]/[[0021]]/[[0036]]/[[0037]] 经 amendment 校准后足以承载
“建议可追踪、用户修改不可覆盖、人工确认入账、provider 最小外发”四个核心决定。

## 实施切片与停止条件

1. 本审查 + legacy 状态/关系校准 + 最小 successor 决策；不改安装器代码。
2. DB lifecycle 代码顺序与 PG 故障测试。
3. Android write-ahead intent、Room quarantine/binding exit 与 mixed-version/crash Android 测试。
4. idempotency stable result + principal binding + PG 并发测试。
5. currency fail-close/binding/capability 与跨端金额测试。
6. 图片同代备份恢复、账务 calendar、家庭 RBAC 分别独立落地。
7. 最后才让 registry/clause/evidence/CI 固化已经确认的决定。

当状态/关系、P0 successor 和 release blockers 已有明确实施切片后，停止继续扩写总纲。后续工作必须转向
数据库约束、代码、测试、CI、恢复演练和实机证据；治理工具不得成为新的业务权威或主线阻断单点。
