# 0042 离线可用性边界 + 请求幂等键（outbox-routed mutate surface）

- Status: accepted
- Date: 2026-06-03
- Decision makers: 项目维护者
- 说明: 本 ADR 是一份已过三方评审 gate（原始方案 → 对抗性审查 → 交叉验证）的设计规范（DRAFT v2）的沉淀；承重事实主张已回代码/schema 核实（见 Confirmation）。

## Context and Problem Statement

ADR-0038 把乐观并发（OCC）铺到所有 mutate endpoint，ADR-0041 把 CAS token 升为 `row_version`。Android 侧 ADR-0038 PR-2g 建了离线 outbox：带 token 的写操作直连失败（`IOException`）时入队、联网后 replay。

这套机制有一个结构缺口——**committed-but-unseen**：

- `saveExpenseAllowingOffline` 是 **direct-first**（先直连 `PATCH /api/expenses/{id}`，仅 catch `IOException` 才 enqueue，已核实 `ExpensePendingRepository:111`）。
- 若 direct PATCH **已在服务端 commit**、但响应在网络上丢了，客户端此刻才入队，replay 带的是**旧** `expected_row_version` → 服务端 `row_version` 已变 → 走 `state_conflict` → **假 409**。
- 单条编辑现在就有这条遗留假冲突；批量改（一次 N 笔）会把它放大到 N 条。

根因：**OCC 与请求幂等是两个不同机制，不能互相替代。** OCC（`row_version`）解决*并发写保护*（两客户端基于同版本改同行，防丢更新）；请求幂等键解决*同一操作的安全重放*（请求已提交、客户端没看见结果再发一次，不重复副作用、不误判冲突）。OCC 本身**不保证**幂等——上面那条假 409 就是活证据（对标 AWS HealthLake：ETag 做 OCC + idempotency key 做去重，二者共存）。

此缺口从「批量改已确认账单分类/标签该不该离线」这个特性决策下钻而来。本 ADR 是底座层规范，不引入新业务功能。

> 与 ENGINEERING_RULES §14 的关系：§14「当前阶段不引入」列了「`client_request_id` 幂等键」。本 ADR 为 **outbox-routed mutate 面**引入服务端请求幂等键，是该 deferral 的**解除触发器**（§13 规则演进：不做→做 须 ADR + 主规范 version bump）。范围限于 outbox-routed mutate，不是给所有写操作加 client-side dedup key。

## Decision Drivers

- §0 #1 数据正确优先：假 409 是正确性缺陷，不是体验瑕疵。
- 离线可用性是真需求：主理人确认手机改账「网络时有时无」，批量改若只能联网用本身即破坏体验。
- 开发期、无稳定安装基数：现在加底座（含破坏性 schema/契约改动）成本最低。
- §6 同步幂等 / §7 并发写版本号保护 / §3 幂等（写操作可安全重试）。
- 复用已有机制优先：冲突收敛用 outbox 现成的 keep-mine/drop-mine，不新设计冲突 UI。

## Considered Options

- **A. 维持现状（仅 OCC）**——继续接受 committed-but-unseen 假 409（单条已有、批量放大）。
- **B. 内容派生 dedup key**——用 payload hash 去重。否：category/tags 可被改回又改去，内容 hash 会误去重（A→B→A 被当重复）。
- **C. Stripe 式通用 response cache**——逐字节缓存首次响应（含 5xx）。否：本仓库要的是 outbox mutation 去重表，不是响应缓存；缓存错误响应会困住客户端、挡住成功重试。
- **D. 请求幂等键层，覆盖面 = 实际 outbox-routed set（本 ADR 选）**——独立表 + intent 时刻 UUID + header 传输 + key 命中先于 OCC；只覆盖真正会入队 replay 的那批 mutate。

批量改的子决策：**客户端 fan-out（路 X，选）** vs 服务端 fan-out / 原子 batch 端点（路 Z，否）。路 Z 否的硬理由：在线走 batch 端点、离线走单条，两端点间幂等键跨不过去 → committed-but-unseen 的 N-冲突窗口结构性焊不掉；且主理人确认「全成或全不改」非 category/tags 真需求。

## Decision Outcome

Chosen: **D + 路 X**。

**边界判据（升为契约，§2）**：带 `expected_row_version` 的 mutate route 是进 outbox 的**必要非充分**条件（候选池）；不带 token 的 create / terminal lifecycle / 自带 contract 的 batch → online-only。某 route 是否**实际**需要幂等键，由三条客观测试判定：① 被 `*AllowingOffline`/direct-first 路径 enqueue；② outbox row 持久化且可能因 IO/timeout 重放；③ 该重放会被旧 token 误判 `state_conflict`。三中全中 → 接幂等键。此判据原是作者写在 `PendingMutationType.kt` 注释里的明文，本 ADR 沉淀为契约。

**覆盖面 = 实际 outbox-routed set（11，非 enum 16）**：已核实 AppContainer 注册面 == dispatcher 文件面 == `*AllowingOffline` 变体面 == 11（PatchExpense/Confirm/Reject/MarkNotDuplicate/RetryOcr/ReplaceItems/AcknowledgeItemsMismatch/UpdateCategoryRule/DeleteCategoryRule/UpdateMerchantAlias/DeleteMerchantAlias）。enum 里其余 5 个未接 dispatcher/callsite，不入队。

**幂等键机制（§4）**：独立表 `api_idempotency_keys`（UPDATE 无新行可挂 key，对比 INSERT 专属的 `draft_idempotency_key`），`UNIQUE(tenant_id, idempotency_key)`；key 在**用户 intent 时刻**生成 UUID v4（非 enqueue 时——committed-but-unseen 发生时还没入队），direct 请求与后续 outbox row 带同一 key；HTTP `Idempotency-Key` header 传输；服务端**先查/claim key 再走 OCC**，命中 `succeeded` 直接返回**不再查 row_version**（堵假 409），并发同 key 用原子 `INSERT ON CONFLICT` 占位 `in_progress`（撞到的退避重试或有界等待，绝不并行 mutate，含超时回收）；幂等记录与业务 mutation **同一 `db.commit()`**；命中返回 **canonical success shape**（按 resource 当前状态重建、与首发响应同构，非复刻历史 body）；fingerprint（operation+target+canonical body+expected_row_version）不符 → 422 `idempotency_key_reused`；**只记录已提交成功**的 mutation（validation/OCC 409/permission/commit 前 5xx 不写）。

**KeepMine 旋转新 key（§4.8）**：冲突后 KeepMine 改了 `expected_row_version` 已是「看过冲突后覆盖新版本」的新意图 → 旋转新 idempotency key（否则 fingerprint mismatch，或为迁就它把 token 排除出 fingerprint 而搞脏 OCC）。

**保留期绑 outbox 滞留窗口（§4.10，正确性约束）**：retention 必须 ≥ 一条 unresolved outbox row 还可能重放的最长时间（key 在该行还可能 replay 时绝不能先过期，否则重放变新操作、双重应用）。但实测该上限**不完全可推导**：outbox 只 GC DONE 行（7 天），PENDING 行在「长期离线」下不被任何 GC 回收，理论上无界。故实现取**保守常量 30 天**（> 7 天 DONE GC、覆盖现实离线窗口；极端长尾超出后退化回原假 409，可接受），不抄 Stripe 24h。要让下界**真正可推导**，需在 keys 实际写入（Slice B/D/F）前给 outbox PENDING 行加 age-cap + 到期 key GC——本 ADR 列为 keys 上线前置（见 More Information）。

**批量改 = 客户端 fan-out（路 X，§6）**：选中 N 笔 → 拆成 N 条独立 `PatchExpense`（真 per-expense target `expense:<id>`），与同笔单条编辑天然 same-target serial 串行，无需扩展 outbox 核心；每条带自己的 intent-time key。在线/离线统一 fan-out，放弃原子全滚（部分成功 + 「M 笔被改过未动」对本场景反而更对）。`ConfirmedBatchUpdate` enum 项作孤儿清掉（未实际接入；token-carrying，未来真做离线批改要一起接幂等键）。

**冲突收敛复用现成机制（§2.5）**：撞 409 → `DispatchResult.Conflict` → CONFLICT 行 → 用户在 SyncStatusScreen 选 keep-mine/drop-mine。非 last-writer-wins 静默覆盖。不为离线化操作新设计冲突 UI。

**goals / income-plan 离线化（§7.1.2）**：带 token + 多设备会改 + 现成 keep-mine/drop-mine 兜底（撞了变 CONFLICT 让用户决定、不静默吞）→ 安全离线（补 `AllowingOffline` + dispatcher + 幂等键）。推翻早前「保持 online-only / 需单独立项设计冲突」的临时建议（见下文）。

**未来强制规则（§2.4）**：任一 token-carrying route 新增 `AllowingOffline` + 接 outbox，**必须同步接幂等键**——否则制造新的 committed-but-unseen 缺口。

## Consequences

Good：
- 闭合 committed-but-unseen 假 409（单条遗留 + 批量放大）。
- 批量改离线可用且复用全部现有 outbox 机器（dispatcher/cascade/keep-mine/same-target serial），零 outbox 核心扩展、零新 dispatcher。
- goals/income-plan 安全离线化；离线可用性边界从「散在注释的隐式判据」升为显式契约 + CI 可校验。

Bad / 成本：
- 新表 + 迁移；每个 outbox-routed mutate route 都要穿幂等键（Slice B/D）；服务端对 outbox-routed mutation 强制 key-present（无则 422）。
- retention 与 outbox 参数耦合（正确性约束，不是纯清理策略）；KeepMine 多一条「旋转 key」纪律；多一层 fingerprint 逻辑。
- 跨端契约新增 header（Android DTO/ApiService + 后端 + 审计同步）。
- stale-`in_progress` 回收有一个**有界双重应用长尾**：两个请求同时撞上同一条已超时（owner 崩溃）的占位行可能都 reclaim → 双重 mutate。属极端长尾（需 >stale 阈值的崩溃 + 并发重试），当前接受；keys 上线前可用「带条件的 reclaim UPDATE + rowcount 守卫」收紧。
- retention 下界**不完全可推导**（PENDING 行无界，见 §4.10）：当前取保守常量 30 天，真正可推导需先给 outbox PENDING 行加 age-cap（keys 上线前置）。

回收条件：本层是正确性底座，回退会重新打开假 409 缺口，不轻易可逆。若边界判据本身变化（如改用不同同步模型），另写 ADR 重评。

## Confirmation

- **committed-but-unseen 测试（PG lane）**：PATCH 已 commit、模拟响应丢失 → 同 key + 旧 token replay → 返回 canonical success（**非** 409）。
- **并发同 key**：两个同 key 请求 → 恰一个 mutate，另一个走 `in_progress`（409 或有界等待）、无双重应用；`in_progress` 占位有超时回收。
- **fingerprint mismatch** → 422 `idempotency_key_reused`；**KeepMine 改 token** → 旋转新 key、不误判 mismatch。
- **只记成功**：validation/OCC-409/permission/commit-前-5xx 不写成功记录（后续合法重试仍能成）。
- **retention 下界**：在真正写 key 的 slice 里断言 retention ≥ outbox 可推导滞留上限（含届时新增的 PENDING age-cap）；Slice A 仅设保守常量 30 天（§4.10），无 live key 故零暴露。
- **覆盖面审计**：扩展 mutate-token 审计（或新审计 lane）——每个 outbox-routed mutation 同时带幂等键，边界契约在 CI 强制。
- **批量 fan-out**：选 N 笔 → N 条 PatchExpense、same-target serial 保住、部分成功如实反馈。

## More Information

- [[0038]] Multi-Surface Sync——OCC 是并发层，本 ADR 的幂等键是互补的重放层。
- [[0041]] PostgreSQL + row_version——本 ADR 建立在 `row_version` token 之上。
- 分层 dedup 现状（§3）：notification draft（`draft_idempotency_key` + unique index）、CSV import（`(batch_public_id, line_number)`）已有各自 dedup；manual create 是 online-only 无 key；outbox-routed mutate 由本 ADR 补幂等键。措辞纪律：**不能写「create 都已 dedup」**。
- 落地切片（一个一个 PR）：核实 ✅ → A（`api_idempotency_keys` 表 + FastAPI 通用 helper + Android outbox schema 加 `idempotencyKey`）→ B（PATCH expense 接入，顺修单条遗留冲突）→ C（批量改 fan-out + 清 `ConfirmedBatchUpdate` 孤儿）→ D（confirm/reject/mark-not-duplicate/retry-ocr/rules/aliases 全覆盖）→ E（补 ReplaceSplits/RecognizeText 离线闭环 + 幂等）→ F（goals/income-plan 离线化）。schema/helper 按 outbox-routed set 通用设计，接入面严格收窄到该 set（≠ enum 全集）。
- **keys 上线前置（§4.10 / Consequences）**：Slice B/D/F 真正写 idempotency key 之前，给 Android outbox PENDING 行加 age-cap + 到期 key GC sweep，使 retention 下界从「保守常量」变「可推导」；同期可把 stale-`in_progress` reclaim 收紧成带 rowcount 守卫的条件 UPDATE。
- 勘误留档（对抗性审查纠错）：① `ConfirmedBatchUpdate` 非 preview_token，排除理由是「未实际接入的孤儿」而非「自带 contract」（schema 带 `expected_row_version_by_id`，是 token carrier）；② goals/income-plan 早前「保持 online-only/需单独设计冲突」基于错误前提（以为多设备改会被静默覆盖），实际有现成 keep-mine/drop-mine 兜底 → 可安全离线。
- 治理：本 ADR accepted 后须更新 ENGINEERING_RULES §14（移除/改写「不引入 `client_request_id` 幂等键」条，注明 outbox-routed mutate 面已由本 ADR 引入幂等键）+ 主规范头部 version bump（§13 规则演进：MINOR/MAJOR 由维护者定）。
- ENGINEERING_RULES §0 / §3 / §6 / §7 / §11 / §14。
