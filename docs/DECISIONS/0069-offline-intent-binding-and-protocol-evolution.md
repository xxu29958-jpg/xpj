+++
schema_version = 2
id = "0069"
title = "离线意图、绑定退出与跨版本重放协议"
summary = "把可重建 Room 投影与不可静默丢弃的用户意图分离，以版本化 envelope、绑定退出 ceremony、OCC 和稳定幂等结果保护长期离线多端写入"
current_scope = "Android Room confirmed cache/outbox、账本或会话切换、离线 mutation 重放、mixed-version API 与客户端 schema 演进；不引入 peer-to-peer 或 CRDT"
date = "2026-07-11"
decision_status = "accepted"
implementation_status = "nonconformant"
verification_status = "failed"
decision_type = "data-consistency"
risk_level = "critical"
confidence = "high"
decision_owner = "owner / 项目维护者"
implementation_owner = "Android 数据层、后端 mutation/idempotency 与跨端协议维护者"
verification_owner = "独立数据正确性 reviewer + Android migration/PG concurrency CI"
risk_owner = "owner / 项目维护者"

[[relations]]
kind = "refines"
target = "0038"
scope = "Room confirmed 投影与 outbox intent 分离、绑定退出、冲突与按聚合 tombstone 语义"

[[relations]]
kind = "refines"
target = "0042"
scope = "committed-but-unseen、intent-time 幂等键、长期离线保留和重放过期后的人工 rebase"

[[relations]]
kind = "refines"
target = "0057"
scope = "稳定首次结果 envelope、principal/device binding、同事务 claim 与客户端 causal token 消费"

[[relations]]
kind = "refines"
target = "0061"
scope = "离线金额命令必须绑定 installation home-currency/minor-unit 语义 revision，禁止客户端默认或权威换算"

[[relations]]
kind = "refines"
target = "0066"
scope = "家庭账务事实系统中多端写入和离线冲突承重域的可执行协议"
+++
# 0069 离线意图、绑定退出与跨版本重放协议

## [ADR-0069-SCOPE] Context, Scope and Non-goals

小票夹现在是家庭账务事实系统：同一账本可以由 Android、Web 和后台入口写入，客户端可能跨多个发布长期离线，
而 PostgreSQL 中的财务事实、家庭身份和权限会继续演进。离线能力保护的不是“一个上传请求”，而是用户在某个
server/account/device/ledger 绑定下、基于特定财务与协议语义作出的**尚未被服务端确认的命令意图**。

当前 Android 已具备正确方向的一部分：`pending_mutations` 持久保存 `serverUrl`、`ledgerId`、mutation type、payload、
`expectedRowVersion` 和 `idempotencyKey`；DAO 按 binding 读取、同 target 串行；dispatch lease 防止换凭证时用新 session
发送旧行。但是三个已证实的实现会丢失或误解释用户意图：

- `AppDatabase.MIGRATION_10_11_STATEMENTS` 在把 OCC token 从 ISO 字符串改成整数时执行
  `DROP TABLE IF EXISTS pending_mutations`，把无法自动重放的 legacy intent 当成 cache 删除；
- `ExpenseRepositoryCore.clearBinding()` 调用 `withBindingTransition(clearExistingRows = true)`，最终执行
  `PendingMutationDao.clearAll()`；退出只显示普通确认框，不展示未提交数量、作用域或 Sync/Preserve/Discard 选择；
- 当前 outbox 行没有 payload schema、API contract/capability、稳定 server/account/device identity、installation home-currency
  revision 或 accounting-timezone revision；旧 payload 可能被新代码用新默认值解释。

本 ADR 决定 Room confirmed 投影、离线 intent、binding lifecycle、payload/version、OCC/idempotency、tombstone、迁移和
mixed-version 的边界。它不把所有命令改成离线可用，不让 Room 成为服务器事实源，不实现客户端之间直接同步，也不
引入 CRDT、通用 event sourcing 或多 active-backend writer。某个领域命令是否允许离线，仍须由该聚合的权限、冲突和
补偿契约明确授权。

## [ADR-0069-ASSUMPTIONS] Assumptions and Applicability

- PostgreSQL 是结构化账本事实、权限、服务端 tombstone 和已提交命令结果的唯一在线权威；Room 不裁决服务端事实。
- 当前服务端拓扑是一套 PostgreSQL、一个 active writer；Android 可以有多设备、多账本和长时间离线实例。
- Room 文件和 Android 私有目录可能因卸载、用户明确清数据或设备损坏而消失；“离线 intent 可持久”不等于跨卸载备份。
- 服务端在认证后能返回稳定 server identity、当前 principal/device/ledger binding、协议 capability、服务器 UTC、账本
  财务语义 revision 和支持的 replay window；只有 URL 或 app 版本名不能充当这些证明。
- 设备 wall clock 可能错误、回拨、跨 DST 或在关机期间停止；它不能独立决定财务时间、幂等过期或意图删除。
- 当前 home currency 由 [[0061]] 决定为 installation-global 固定语义，而 accounting timezone/calendar 是 ledger-scoped；
  两类解释一旦允许改变都必须产生各自单调 revision 并有迁移 ADR，不能只改环境变量后让旧 intent 被重新解释。
- 若未来需要多 active backend、跨服务端迁移或共享设备多 OS 用户，必须先补 fencing、server identity 迁移和本地数据
  隔离契约；不得把当前单 writer/单 Android profile 前提静默外推。

## [ADR-0069-DRIVERS] Decision Drivers

- 未提交 intent 是用户工作成果。无法自动执行不等于可删除；宁可阻塞、隔离和让用户 rebase，也不能伪造成功。
- confirmed cache 可重建，intent 不可从 PostgreSQL 重建；两者需要不同删除权限、迁移和 UI 语义。
- OCC 防止基于旧事实覆盖新事实，幂等防止同一意图重复执行；任何一个都不能替代另一个。
- 新旧客户端、backend、Room schema、payload 和账本财务语义不会天然同版，重放前必须协商而不是猜默认值。
- 切换账本、退出账号和清理离线副本是不同操作；作用域和副作用必须在最后一个并发写入点之后再次确认。
- 长期离线和设备时钟错误是正常失败路径，不得用“通常七天内上线”作为数据正确性前提。
- 家庭自托管仍需有界队列、背压和可解释操作，不能用无限保留或无限并发把服务拖垮。

## [ADR-0069-ALTERNATIVES] Alternatives

### [ADR-0069-ALT-A] A. 保持 cache/outbox 同清理、migration 无法转换就 drop

拒绝。它实现简单，却把“服务端可重建投影”和“服务端从未见过的用户命令”混为一类；升级、退出或调试 rebind 都可能
不可逆丢失金额、分类、确认或人工修订。

### [ADR-0069-ALT-B] B. 永久保存旧行，并让新客户端按最接近的新 DTO 猜测重放

拒绝。保存 bytes 只解决可取证性；把字符串 token 伪装成 `0`、缺省币种为 CNY、缺省时区或忽略未知字段，会把原意图
变成另一条财务命令。错误执行比显式阻塞更危险。

### [ADR-0069-ALT-C] C. 客户端以 last-write-wins/CRDT 自动合并所有财务写入

拒绝。金额、确认、债务、分账、删除和权限变更不是可无损交换的通用字段集合；自动合并会绕过人工确认、聚合不变量和
服务端权限。当前规模也没有引入通用分布式合并引擎的收益。

### [ADR-0069-ALT-D] D. 版本化 intent envelope + legacy quarantine + 显式 binding-exit ceremony

选定。已知、安全且仍受支持的 intent 才可重放；未知或过期 intent 完整保留并进入人工 rebase。缓存、凭证和 intent
分别处置，服务端继续通过权限、OCC、幂等和聚合事务作最终裁决。

## [ADR-0069-DECISION] Decision

选择 D。离线子系统由三个不同存储身份组成：可重建的 confirmed projection、尚未提交的 versioned intent，以及只用于
保全和人工处置的 legacy quarantine。任何代码路径、Room migration 或 UI 操作都必须保持这三者的身份。

### [ADR-0069-C01] Confirmed projection、intent 与 quarantine 分权

- `confirmed projection` 是某个 server/account/ledger 的服务端事实快照。它可按 binding 删除并从 PostgreSQL 重建，
  不得被当成离线写入证明；清 cache 只能清这类投影及其 sync cursor/thumbnail。
- `outbox intent` 是用户明确发出的、尚未取得稳定服务端成功结果的本地持久命令。它不是 cache，不得因刷新、退出、
  换账本、换 URL、migration 无法理解、队列过龄或清离线副本而静默删除。
- `legacy quarantine` 完整保存不能证明可安全重放的历史行、原 schema version、原字段类型和值、导入时间、来源 binding
  线索和不可变内容 hash。它永不自动 dispatch，也不参与 optimistic projection；只有显式 converter/rebase/discard 能
  改变其状态。
- `DONE` 或稳定结果 receipt 只证明对应 intent 已由 PostgreSQL 接受。客户端确认结果并刷新/合并服务端版本后，可按
  retention 清理本地 intent；不得先删 intent 再假设网络响应一定可见。
- 任何“清本地数据”交互必须分别列出 confirmed projection、未提交 intent 和 quarantine 的数量与后果；一个布尔
  `clearAll` 不能同时表达三种授权。

### [ADR-0069-C02] 每条新 intent 使用自描述、不可歧义的 envelope

新 outbox schema 至少持久化以下字段；字段存在不代表客户端成为权威，服务端仍逐项验证：

| 类别 | 必需内容 | 约束 |
| --- | --- | --- |
| identity | `intent_id`、`server_identity`、`account_id`、`device_id`、`ledger_id` | 不用可变 URL、显示名或当前 session 猜 binding；token 不入 payload |
| protocol | `intent_schema_version`、`mutation_type`、`payload_schema_version`、`api_contract_version`、required capabilities | 未知值 fail closed；type 与 decoder 明确一一对应 |
| causal | 聚合类型/ID、durable local sequence、`expected_row_version` 或领域等价 token | `0` 只能是该命令明确定义的“无 prior row”，不能表示迁移失败 |
| replay | intent-time `idempotency_key` 或该 create 命令已审定的稳定 `client_ref`、canonical fingerprint | direct/replay 使用同一 identity；Keep Mine/rebase 是新 intent/new key |
| finance | 显式 amount minor unit + currency；`installation_currency_binding_revision`；必要时 FX policy/rate reference | 禁止 float、隐式 CNY、客户端权威换算或用最新汇率重解释旧命令 |
| accounting time | 原始 instant/local date/zone/offset 中该命令要求的字段、`accounting_timezone_revision` | 不用设备当前时区或后来修改的环境变量重切账期 |
| retention | 客户端观察时间、最近一次可信 server-time anchor、服务端给出的 `replay_not_after`（得到后） | device wall clock 仅作诊断，不独立触发删除/dispatch |
| integrity | canonical payload bytes/hash、envelope version、创建代码 build/protocol identity | migration/converter 必须证明未改变原语义 |

payload 必须使用逐 mutation 的显式 DTO/schema；“任意 JSON + enum”只可作为 storage container，不能成为扩展契约。新增
mutation type/version 必须有真实 decoder、capability、权限、OCC/idempotency、conflict UI、mixed-version 和退役测试。
删除或重命名字段遵循 expand → migrate → capability gate → contract，不把未知字段静默丢弃后继续发送。

### [ADR-0069-C03] 先持久化 intent，再发送；optimistic UI 只是其投影

- 离线允许的用户命令在第一次网络尝试前，先在一个 Room transaction 中写入完整 intent 和必要的 local optimistic
  projection。transaction 失败时 UI 必须报告“未保存/未发送”，不能只改内存后显示排队成功。
- intent-time idempotency identity 在第一次发送前生成并持久化；direct attempt 与 WorkManager replay 都读取同一行。
  禁止“先直连，遇到 IOException 才临时创建另一条意图”，否则 committed-but-unseen 无法证明是同一次操作。
- 本地 UI 展示值由 `last confirmed projection + 当前 binding 下仍有效的 intent overlay` 计算。收到服务端成功后以稳定
  result token 合并；Drop/Rebase/Conflict 后重新计算，不能把 optimistic 值写成 confirmed authority。
- 同一聚合按 durable local sequence 串行。sequence 由 Room transaction/单调本地计数产生，不以 wall-clock 字符串排序；
  不同聚合可以在声明的全局并发上限内并行，权限/账本级命令可声明更宽 serialization key。
- 数据库空间不足、序列化失败、未知财务 revision 或 key 生成失败时 fail closed，不发请求、不做 optimistic success。

### [ADR-0069-C04] 账本切换、退出和清理采用显式四路 ceremony

binding key 至少是 `server_identity + account_id + device_id + ledger_id`。server URL、session token 和 active ledger 是
binding 的当前入口，不是 identity。所有退出交互先展示作用域内 `PENDING/IN_FLIGHT/CONFLICT/FAILED/expired/quarantine`
数量、最老观察时间、可能影响的命令种类和数据是否仍在，然后提供以下动作：

- **Sync**：在旧 binding/旧 credential 仍有效时 drain；可自动完成的全部取得稳定结果后再退出。conflict、permission、
  capability 或过期项必须回到用户处理；不能为完成退出而自动 Keep Mine/Discard。
- **Preserve**：停止 dispatch，把 exact binding 的 unresolved intent 标为 parked，保留原 payload/hash/identity。以后只有重新
  认证到同一稳定 server/account/device/ledger 且重新通过 capability、权限、财务 revision 检查，才能继续或 rebase。
  UI 必须说明本机仍保有私人数据；共享设备上可由安全策略禁止 Preserve，但不得替用户改成 Discard。
- **Discard**：不可逆删除明确 scope 内的 unresolved intent/quarantine；必须二次确认数量、账本和后果。服务端已提交但
  未可见的结果仍可能存在，因此 discard 后重新登录必须从 PostgreSQL refresh，不得用旧 optimistic cache 推断未提交。
- **Cancel**：不改 credential、active binding、cache、intent、worker schedule 或 session epoch。

scope 规则：ledger switch 只针对**当前 ledger binding**，默认 Preserve；它不清其他账本/服务器的 intent。server/account
logout 对该 credential 可访问的**全部 ledger bindings**逐项汇总并选择一项策略，不能用全数据库 `clearAll` 隐式扩域。
“清 confirmed 离线副本”默认只删除 projection，不退出、不撤销 token、不碰 intent/quarantine。

执行最终动作时必须持有 binding-transition lease 与 dispatch/enqueue lease，在锁内再次验证：当前 server/principal/device/
ledger 未变、展示快照 generation 未变、scope 内 unresolved/in-flight 计数仍符合所选动作。Sync 要求计数为零；Preserve
要原子 park 全部；Discard 要按 exact binding 条件删除并核对 rowcount。出现新 enqueue、旧 dispatch 尚未结束、凭证已撤销
或 generation 改变时，动作无副作用地返回“状态已变化，请重新确认”；不得用锁外一次检查后直接清 credential/rows。

### [ADR-0069-C05] Room v14 用 direct migration 保全 v10 legacy intent

- 新 schema 使用独立的 versioned intent table 和 `legacy_pending_mutations_quarantine`；confirmed expense/cache 表继续独立。
- 必须提供并测试 **direct 10→14 migration**。它在删除/重建任何旧表前，把 v10 `pending_mutations` 每列按原类型原值复制到
  quarantine，记录 `source_room_version=10`、row ordinal 和 canonical hash，再校验 source count/hash 与 destination。
- v10 的 `expectedRowVersion` 是 TEXT timestamp token。不得转成 Long `0`、当前 row version 或空 token，也不得因当前
  backend 已改用整数 CAS 自动 replay。它只能由用户查看后基于最新服务器事实显式 rebase 成新 intent。
- 11/12/13→14 同样先保全现有行。只有 converter 能证明 mutation decoder、原 principal/binding、idempotency identity、
  ledger financial revisions 和 backend capability 全部匹配时，才可原子转为 active intent；否则进入 quarantine。
- migration 在单个 SQLite transaction 中执行 `create quarantine → copy → count/hash verify → create v14 tables → switch`；
  任一校验失败回滚并拒绝打开 app 数据层。migration 成功但有 quarantine 行时应用可读 confirmed cache/联网 refresh，
  但必须持续显示待处理入口，不能把 quarantine 数量当作零。
- 当前 10→11 destructive migration 必须从受支持 upgrade graph 中移除/旁路；instrumented test 必须证明 Room 从真实 v10
  schema 选择 direct 10→14，而不是先走 drop 路径。已经被历史 10→11 删除且没有外部备份的行无法恢复，发布说明和
  migration receipt 必须如实记录 `previously_lost_unknown`，不能伪造“v14 已恢复”。

### [ADR-0069-C06] Unknown payload/version/capability 一律保留并 fail closed

- decoder 对未知 mutation type、intent/payload schema、enum、required field、server capability 或账本财务 revision 返回稳定
  `blocked_upgrade_required` / `blocked_rebase_required` / `quarantined_invalid`，不 dispatch、不删除、不套默认值。
- malformed payload 保留原 bytes/hash；诊断只记录 intent ID 摘要、version 和 reason code，不记录金额、备注或 token。
- 新客户端不得因旧 backend 不认识 header/field 就去掉 idempotency、OCC、currency 或 time semantics 后重试；它把 intent
  留在本地并提供升级服务器、导出、rebase 或 discard 的明确选择。
- 旧客户端请求新 backend 时，backend 只在公开兼容窗口内接受旧 contract。无法无歧义升级的请求在任何业务副作用前返回
  稳定 `client_upgrade_required`/`contract_unsupported`；禁止把缺失 currency/timezone/version 当默认值后写入。
- 长期离线客户端上线时，先认证和 capability/ledger-revision handshake，再考虑 dequeue。handshake 失败不是网络重试的
  mutation 失败；队列保持 parked/blocked，人工记账的服务端现状不被本地旧 cache 覆盖。

### [ADR-0069-C07] OCC 与幂等分别保护冲突和重放

- OCC token 绑定用户作决定时看到的聚合版本；服务端在事务内以 `ledger + aggregate identity + row_version` 条件写。
  stale 返回可分类 conflict，不做 last-write-wins。客户端不能用本地 confirmed/optimistic 更新时间生成权威 token。
- 每个可重放 intent 的 idempotency identity 在 intent 时刻生成，绑定原始 ledger/principal/device、operation、target 和 canonical
  fingerprint。它不是 bearer；每次 replay 在暴露命中状态或 locator 前仍做当前认证、成员关系和资源可见性检查。
- claim、业务 mutation 和 [0057] 的最小化首次成功 result envelope 在同一 PostgreSQL transaction 提交或回滚。不得持久化
  可按时间无 fencing reclaim 的 `in_progress`；发现历史异常行 fail closed 并进入 repair。
- committed-but-unseen replay 返回第一次 commit 的稳定 `result_kind/resource_ref/post_row_version`，不重建资源当前状态。
  客户端 causal cascade 只能消费该 `post_row_version`；需要最新资源时另行 GET，不能用后来版本假装首次结果。
- 同 key + 同 fingerprint 只执行一次；同 key + 不同 fingerprint 拒绝；Keep Mine、人工 rebase、改变 token/payload/currency
  semantics 都是用户看过新事实后的**新 intent**，必须新 `intent_id` 和 idempotency key，并链接旧 intent 作审计。
- 服务端 idempotency retention 必须严格长于协议公布的最大 replay window并真实 sweep。key 过期后旧 intent 不再自动发送，
  而进入 explicit rebase；不得因 key 已过期把同一 payload 当新操作盲发。

### [ADR-0069-C08] Conflict 和 tombstone 必须按领域聚合解释

- outbox 层只负责阻塞、顺序和携带证据，不定义通用“覆盖远端”。每个 offline-capable mutation 注册其聚合类型、冲突类别、
  可展示 diff、是否允许 rebase、补偿/撤销边界和 server tombstone 行为；没有注册即 online-only。
- `Keep Mine` 不是把旧 payload 换一个新 token直接覆盖。客户端先拉最新可见事实，展示领域 diff/副作用，用户再次确认后由
  领域 converter 生成新 intent。`Drop Mine` 只终止所选 intent，并从 confirmed projection + 剩余 intents 重算 UI。
- expense 删除/回收、tag merge/undo、merchant merge、debt void/forgiveness、invitation expiry 等不是同一种 tombstone。
  每个聚合分别决定 retention、restore/compensation、子对象引用、旧 command 的 `conflict/noop/rebase-forbidden` 和审计。
- 服务端 tombstone/void/merge 状态属于 PostgreSQL 权威。confirmed cache 收到 tombstone 后必须阻止旧可见行复活；在 tombstone
  之前创建的 intent 不得通过 create/upsert 默认值重建聚合。只有该领域明确授权的 restore/compensation 命令可改变状态。
- tombstone contract/version 未知时保持 blocked；通用 outbox GC、cache prune 或“404=删除成功”不得替某个聚合裁决。

### [ADR-0069-C09] 队列顺序、过龄和时钟错误不造成静默丢失

- 同聚合因果顺序使用 Room 事务生成的 durable sequence；`createdAt` 仅供人类诊断。设备时间回拨、切时区、DST 或重启不
  能重排、提前过期或延长 idempotency safety window。
- 客户端从最近一次认证 handshake 保存 `(server_utc, elapsed-realtime anchor, replay policy/version)`；进程内可用 monotonic
  elapsed 估算，但重启、clock jump 或 anchor 缺失时标 time uncertainty，重新联网校准后再 dispatch。
- 服务端返回/能力声明的 `replay_not_after` 和 key retention 是自动重放上限。达到上限只把 intent 变为
  `expired_action_required`；保留原 payload/hash，禁止后台发送和自动删除。用户 refresh 最新事实后可 rebase 为新 intent，
  或明确 discard/export。
- 现有七天 client age-cap 可以停止自动 replay，但不能成为删除授权；服务端 retention 必须大于该自动 replay window。
  改窗口须同时改 capability、client policy、server sweep 和 boundary tests，不能只改常量。
- 队列达到容量/磁盘水位时对新 offline mutation 背压并明确告诉用户“未保存”，不能删除最老 intent 腾空间。confirmed cache、
  thumbnail 和已安全确认的 DONE receipt 应先按策略回收。

### [ADR-0069-C10] mixed-version 支持矩阵在重放前裁决

| 组合 | 允许行为 | 禁止行为 |
| --- | --- | --- |
| 新 backend + 旧 client | 在公布的 N-1 contract 窗口内按原语义处理；超出窗口在副作用前要求升级 | 用新默认币种/时区/enum 猜旧请求 |
| 旧 backend + 新 client | capability 不足时保留/阻塞新 intent；仍支持的旧 contract 可明确编码发送 | 删除 required field 或降级 OCC/idempotency 以“兼容” |
| 新 Android + 旧 Room rows | direct migration 完整 quarantine；已证明 converter 才激活 | drop、把 TEXT token 变 0、自动 replay |
| 旧 Android + 新 Room schema | 数据库 schema 高于 binary 时 fail closed 并要求升级 | destructive downgrade/recreate 或 fallbackToDestructiveMigration |
| installation currency 或 ledger calendar revision 变化 + 旧 intent | refresh 后由用户/领域 converter rebase；原 intent 保留 | 用当前 home currency、FX、timezone 重解释原 payload |
| 长期离线后重连 | 先 auth/capability/server-time/revision handshake，再按聚合顺序 replay | 先 drain 再发现版本不兼容 |
| backend/schema 已升级、应用回退 | 只有 published compatibility matrix 通过才可写；否则只读/拒绝 | 旧 binary 对未知事实继续写或靠 DB restore 倒退 |
| 未来多 active backend 版本不一致 | 在 migration ownership、shared capability floor 和 fencing ADR 落地前拒绝 | 让不同版本 worker 同时消费同一 intent surface |

最低支持客户端版本不能只按 build number设置；contract、payload、financial revision、tombstone 和 idempotency result envelope
各自有 capability。字段删除/enum 收紧前必须证明仍可 replay 的 intent 和支持窗口内客户端都不再生产旧形态。

### [ADR-0069-C11] 迁移、回滚和退役以 intent 不丢失为成功判据

v14 rollout 顺序固定为：冻结 drain/enqueue → 备份/校验 Room 文件可读性 → direct migration quarantine → count/hash/schema
验证 → 用新 schema 只读打开 → capability handshake → 逐 binding 展示/处理 quarantine → 才恢复 dispatch。任何阶段崩溃后
重启必须能识别 last committed migration state；不得因 marker 缺失重跑 destructive DDL。

迁移成功判据至少包括：旧行数逐 binding/type 对账、原 payload/token bytes hash 一致、新 active table 只有经过证明的行、
unknown row 全在 quarantine、无 worker 在旧 schema 上 dispatch。confirmed cache 行数不作为数据保全判据，因为它可重建。

在 v14 产生任何新 intent 后，旧 binary/旧 Room schema 不能安全回退。首选前滚修复；只有从 v14 启用前的完整 Room 备份恢复，
并证明期间没有新 intent，才能回到旧版本。否则先把所有新/legacy intent 原样导入 quarantine，再由兼容 build 接管。导出
文件是敏感用户数据，必须加密/受 Android 私有存储保护并包含 hash；它不是 PostgreSQL 事实备份。

退役旧 payload/decoder 前必须等待其 replay window 结束、确认 active+parked+quarantine 无可自动处理消费者，并保留人工
只读/export decoder 至少一个支持周期。工具弃维时先双读/对账，不直接删除旧 table 或 converter。

### [ADR-0069-C12] 失败矩阵明确副作用和下一步

| 失败点 | 允许的副作用 | 稳定状态 | 用户/系统下一步 |
| --- | --- | --- | --- |
| intent Room transaction/磁盘满 | 无请求、无 optimistic success | `not_saved` | 清可重建 cache/DONE 或腾空间后重试 |
| direct/worker 请求已 commit 但响应丢失 | PG 可能已写，intent 保留 | `pending_result_unknown` | 同 key replay；返回首次稳定结果 |
| OCC stale | PG 无该命令副作用 | `conflict` | refresh + domain diff；rebase/new key 或 discard |
| auth/成员/设备被撤销 | PG 无该命令副作用 | `blocked_authorization` | 重新认证同 identity；无权时 export/discard，不泄露 key 命中 |
| payload/capability/revision 未知 | 无网络 mutation | `blocked_upgrade_required` 或 quarantine | 升级、受审 converter 或人工 rebase |
| idempotency key 已过 replay window | 不盲发 | `expired_action_required` | refresh 后新 intent 或 discard/export |
| binding switch/logout 中出现新 enqueue/in-flight | credential、binding、rows 均不变 | `transition_changed` | 回到汇总页重新选择 |
| Sync 有 conflict/failed | 已成功项有 PG 结果，失败项保留 | `exit_incomplete` | 逐项处理或改选 Preserve/Discard/Cancel |
| migration copy/hash/schema 校验失败 | SQLite transaction 回滚；旧 DB 保留 | `migration_refused` | 保留文件/诊断，修 converter 后重试 |
| migration 后发现 legacy row | active dispatch 不处理该行 | `quarantine_attention` | 用户查看、rebase/export/discard |
| app downgrade 遇到 v14 | 无 Room 写入 | `client_upgrade_required` | 安装兼容 build；禁止 destructive fallback |
| server tombstone/aggregate lifecycle 改变 | 旧 intent不执行 | domain conflict/blocked | 按该聚合 restore/compensation 契约处理 |

所有错误交互必须说明：命令是否已保存在本机、服务端是否可能已提交、自动重试是否安全、受影响 binding/条数、数据是否仍在、
唯一允许的下一步。不得把通用 IOException、404 或 app crash 映射成“已同步”或“已删除”。

### [ADR-0069-C13] 观测、容量与隐私只证明协议，不泄露意图

- 结构化本地/运行事件覆盖 enqueue committed、dispatch claim/result、stable replay hit、conflict、blocked reason、binding transition
  snapshot/final-check、park/discard、migration count/hash verify、quarantine/rebase 和 cleanup。
- 指标按不可逆 binding 摘要、status、mutation type/version 聚合：queue depth、oldest observed age、blocked/quarantine count、
  replay latency、conflict rate、committed-but-unseen replay、migration mismatch 和 discard count。不得记录 payload、amount、备注、
  merchant、token、idempotency key、server URL、account/device/ledger 原值或图片路径。
- binding transition 和 migration receipt 记录代码 build、Room from/to version、protocol capability、计数、结果和 failure code；
  receipt 是证据，不是 intent/PG 权威，也不能把部分迁移标成成功。
- drain 每批默认不超过 50 条、同聚合并发为 1、全局 dispatch 并发有配置硬上限；429/503/网络错误指数退避并服从
  `Retry-After`。权限、unknown version、OCC conflict 不进入无界自动重试。
- 参考容量至少覆盖一个 binding 10,000 条 unresolved intent：enqueue transaction 和 exact-scope final check 必须有基准与索引，
  不允许加载全部 payload 到 UI/内存；超过参考容量先背压新命令并要求处理，不能 silent eviction。
- 本地 intent/quarantine 跟随 Android app-private storage 和设备锁策略；诊断包默认只含计数/hash 摘要。Preserve/Export 必须
  明示本机仍有私密财务数据，退出 token 不等于这些 bytes 已销毁。

### [ADR-0069-C14] 当前实现处置与发布门禁

| 当前行为/证据 | 影响 | 处置 |
| --- | --- | --- |
| `ExpenseDetailRepository` 先直发、只在 `IOException` 后 enqueue | 首次网络发送与本地落盘之间 crash/断电会丢唯一 key；服务端已 commit 但客户端未见时，用户重试可生成重复财务事实 | **废弃 direct-first**；所有可离线写先原子持久 intent/key，再由同一 dispatcher 发送；修复前为 Android write release blocker |
| `AppDatabase.kt` 10→11 执行 `DROP TABLE IF EXISTS pending_mutations` | 升级不可逆丢失未提交 intent | **废弃/替换**为 v14 direct quarantine；在修复前 Android upgrade release blocker |
| `ExpenseRepositoryCore.clearBinding()` + `OutboxRepository.withBindingTransition(clearExistingRows=true)` 全表删除 | logout 把所有 binding 的 intent 当 cache 丢弃，作用域过宽 | **拆分/收紧**为四路 ceremony + exact scope + 锁内复核 |
| `PendingMutationEntity` 有 binding/OCC/key/status，但无 version/identity/financial revisions | 长期离线/新默认值可能重解释 payload | **保留骨架并修订**为自描述 envelope；unknown fail closed |
| DAO binding-scoped reads、same-target serialization、dispatch/binding mutex | 已能阻止多类 wrong-session/queue-jump race | **保留并加强**稳定 server/principal/device identity 和 generation final check |
| 当前 idempotency 服务按资源 locator/current row replay、存在 stale reclaim | committed-but-unseen 结果漂移或双执行窗口 | **按 0057 收紧**为同事务 claim + 首次稳定结果 + principal/device binding |
| `createdAt`/age cap 参与顺序和过期 | clock 错误或长期离线可提前终止用户工作 | **放宽保留、收紧自动发送**：durable sequence；过期转人工 rebase，不自动删除 |

因此本 ADR 当前 `implementation_status=nonconformant`、`verification_status=failed`。不得通过降低契约、继续宣称“无真实安装
基数”或只补 linter 把状态改绿。解除 release blocker 至少需要：first-write-ahead intent、v14 direct migration、intent/cache 分表、
四路退出状态机、payload/version/revision gate、stable idempotency result，以及 crash/destructive/unknown/mixed-version mutation tests。

## [ADR-0069-CONSEQUENCES] Consequences

Good：升级、退出和切换不再静默丢用户未提交工作；旧 payload 不会因币种、时区、CAS 或 DTO 演进被改写语义；
committed-but-unseen、并发冲突和 binding race 有互补的数据库/客户端边界；confirmed cache 仍可轻量清理重建。

Costs：Room v14 需要新 active/quarantine schema、direct legacy migrations、四路 UI、binding identity/capability handshake 和更多
领域 conflict converter；后端必须补稳定 result envelope 与财务 revision。旧行不能全部自动 replay，用户可能需要人工 rebase。

Limits/Residual risks：应用被卸载或 Android data 被明确清除仍会失去纯本地 intent；已被历史 10→11 drop 的行无法凭文档恢复；
设备被攻破可读取本地明文业务内容；Preserve 会留下隐私数据；服务端之外的跨设备 intent 备份不在本 ADR 范围。

复杂度约束：不为每个 DTO 建新表，不引入通用 CRDT/事件总线，不允许 outbox 自己决定领域 merge。若 versioned envelope、
quarantine 和四路 ceremony 的实现成本超过被保护的真实离线命令面，应收窄“允许离线”的 mutation 集合，不能退回 silent drop。

## [ADR-0069-REVERSIBILITY] Reversibility, Replacement and Retirement

confirmed cache、Room/WorkManager 实现和 UI 可替换；“未提交 intent 不是 cache”“未知语义不自动执行”“服务端最终裁决”不可
回退。v14 在产生新格式 intent 后是 forward-only：旧 app 无法安全解释，应用回滚须先由兼容 build quarantine/export 全部新行。

未来若使用另一移动数据库或云端加密 intent vault，采用双写/对账/切读/退役迁移，并保留 stable intent identity、原始 bytes/hash、
binding、financial revisions 和结果 receipt。若产品明确取消离线 mutation，必须先 Sync/Preserve/Export/Discard 清零所有 active
和 quarantine 消费者，再移除 worker；不能用 app update 删除队列完成退役。

复审触发：支持多 active backend、跨 server 搬迁 binding、home currency 改为 per-ledger、账本 timezone 可变、端到端加密、多 OS profile、客户端
间直接同步、最大离线窗口改变、Room/WorkManager 被替换，或出现错 binding replay/静默丢 intent/重复财务副作用事故。

## [ADR-0069-EVIDENCE] Verification and Evidence

- Android migration test 从真实 v10 fixture 写入 TEXT OCC token、unknown type、Unicode payload 和多个 binding，直接升级 v14 后逐字节
  hash/count 相同且全在 quarantine；mutation probe 删除 direct migration 或恢复 DROP 必须失败。
- Android migration matrix 覆盖 10/11/12/13→14、崩溃/重启、hash mismatch、磁盘满和 downgrade；明确断言不启用
  `fallbackToDestructiveMigration`，旧 binary 遇 v14 fail closed。
- binding state-machine test 覆盖 Sync/Preserve/Discard/Cancel、ledger-current vs logout-all-ledgers scope、新 enqueue/in-flight 插入、
  credential revoke 和锁内 generation mismatch；任何失败均不发生全表 clear 或 wrong-session dispatch。
- payload mutation tests 删除/未知 `payload_schema_version`、currency/timezone revision、capability 或 decoder 时，行保持且无网络调用；
  old/new backend-client 组合得到稳定 upgrade/rebase 错误而非默认写入。
- PG 并发测试覆盖同 key exactly-once、rollback 后重试、第三方 v2→v3 插写后 replay 仍返回首次 v2 result、principal/device 被撤销
  后不泄露 key 命中，以及无持久 stale `in_progress` reclaim。
- 领域 conflict tests 分别覆盖 expense tombstone、tag merge、merchant merge、debt void/forgiveness 和 invitation expiry；旧 cache 不复活，
  未授权聚合没有通用 Keep Mine。
- clock/property tests 随机 wall-clock 回拨、DST、时区切换、重启和 server-time anchor 缺失；durable order 不变，intent 只阻塞不删除。
- 实机故障演练：enqueue 后 kill、request commit 后断网、binding transition 中 kill、Room migration 中断、七天以上离线后重连；对账
  PostgreSQL stable result、active/quarantine counts、UI 副作用说明和无敏感日志。

反向验收：任一 cache clear/logout/migration 可无 scope 地删除 unresolved intent；任一未知 payload/revision 会被默认解释；旧 cache
能覆盖 PostgreSQL/tombstone；同 key replay 返回第三方后来版本；或设备 wall clock 能让 intent 自动消失，均证明本 ADR 未成立。

## [ADR-0069-REFERENCES] References

- [[0038]] 多端 OCC、Room outbox 和冲突 UI 的原始边界。
- [[0042]] committed-but-unseen 与 intent-time idempotency identity。
- [[0057]] 首次稳定结果、同事务 claim 和 principal/device binding。
- [[0061]] home currency 与 minor-unit 财务语义。
- [[0066]] 家庭账务事实系统与离线意图/缓存身份分离。
- [Android Developers — Migrate your Room database](https://developer.android.com/training/data-storage/room/migrating-db-versions)
- [Android Developers — Define work requests](https://developer.android.com/develop/background-work/background-tasks/persistent/getting-started/define-work)
- [Google AIP-180 — Backwards compatibility](https://google.aip.dev/180)
- [PostgreSQL — Transaction isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
