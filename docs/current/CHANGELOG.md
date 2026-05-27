# Changelog

所有版本都保持 `identity_schema=v0.3` 不变。

## v1.3 主线（开发中） — ADR-0038 多端同步：optimistic concurrency 普及

进行中，未发布 tag。聚合 PR-1（category_rule）/ PR-2a-d（expense PATCH / 状态机 / items / splits / OCR retry / batch update）/ PR-2e（residual mutation）：

- **PR-2e residual mutation**：
  - `/api/expenses/{id}/recognize-text` 改为 client-supplied token：`ExpenseRecognizeTextRequest` 加必填 `expected_updated_at`；service 不再 self-claim，atomic claim 由 client snapshot 驱动；stale → `409 state_conflict`，非 pending → `404`。
  - `/api/expenses/{id}/items/acknowledge-mismatch`：route 新增必填 body `ExpenseAcknowledgeItemsMismatchRequest`；service 改用 `claim_row_with_token` + `extra_where=(items_sum_status='mismatch_known',)`；rowcount=0 三分支 404 / `items_sum_not_in_mismatch` / `state_conflict`。
  - `/api/merchants/aliases/{public_id}` PATCH/DELETE 接 `expected_updated_at`（DELETE 同 PR-1 category_rule 模式带 body）；`/web/merchants/aliases/{id}/toggle|delete` 模板加 hidden token + redirect "页面已过期/已在其它端修改"；Android `MerchantRepository` 强制 `expectedUpdatedAt` 参数。
  - Android `ExpenseDetailRepository.acknowledgeExpenseItemsMismatch` 加 token；`ExpenseEditViewModel.acknowledgeItemsMismatch` 从 baseline expense.updatedAt 取。
  - 测试：三套独立 contract test（`test_recognize_text_optimistic_concurrency.py` / `test_acknowledge_mismatch_optimistic_concurrency.py` / `test_merchant_alias_optimistic_concurrency.py`），每套覆盖 missing 422 / stale 409 / status-specific 409 / two-session race / unknown 404；现有 OCR / items / merchant_aliases tests 全部补 token。
  - OpenAPI snapshot 同步；ADR-0038 段落把 recognize-text / acknowledge-mismatch / merchant_alias 纳入"所有 mutate"清单。

- **PR-1 Android + /web/rules 适配补齐**：
  - PR-1 (ADR-0038 category_rule) 落地后留下两条遗留，本 PR 一并修：
    - Android `updateCategoryRule` / `deleteCategoryRule`：新增 `CategoryRuleUpdateRequest` / `CategoryRuleDeleteRequest` DTO；`ApiService.deleteCategoryRule` 用 `@HTTP(hasBody=true)` 携带 body；`RuleRepository` 强制 `expectedUpdatedAt` 参数；`CategoryRulesViewModel` 调用处从 `rule.updatedAt` 传入；fixtures + DTO contract test 同步。
    - `/web/rules/{id}/toggle|delete` 模板加 hidden `expected_updated_at`；route 接 form-token + `parse_form_updated_at_token` + state_conflict redirect。原 "loopback only no race window" 假设已被 ADR-0028 PR-4 cookie session 打破，跨 window race 真实存在。

- **PR-2e release_audit 新规则**：
  - `backend/scripts/_audit_mutate_token_coverage.py`：走 in-process OpenAPI schema 扫所有 mutate route (POST/PUT/PATCH/DELETE)，验证每个都 carry `expected_updated_at` / `expected_updated_at_by_id`；ALLOWLIST 列豁免（create / terminal lifecycle / batch / admin / preview / single-writer maintenance）每条带 one-line reason；KNOWN_GAPS 标 6 个 v1.1 pre-ADR-0038 sediment route（goal PATCH / income-plan PATCH/DELETE / budget PUT / dashboard PUT / ui-preferences PUT）只 WARN 不 FAIL，未来 strict 模式可加 `XPJ_AUDIT_MUTATE_TOKEN_STRICT=1` 收紧。
  - 已接入 `release_audit.py` 自动 discovery，跑过 138 个 mutate route 全分类（27 token / 105 ALLOWLIST / 6 KNOWN_GAPS）。

- **PR-2g.1 codex round-3 fix**（PR-2g.1 codex 三审 3 个 P2 + 1 个 P3 收尾）：
  - **[r3 P2#1] dequeue starvation → SQL NOT EXISTS**：新 DAO method `nextRunnableBatch(pending, in_flight, conflict, failed, limit)` 把 unresolved-target 过滤推到 SQL 层，`LIMIT` 在过滤之后才应用。原版"Kotlin 后过滤"在前 25 PENDING 都是 CONFLICT-blocked 同 target 的场景会饿死后续 target；新版直接 SQL 跳过。新增 contract test `blockedTargetsDoNotStarveOtherRunnableTargets`（构造 30 个 blocked + 1 个 runnable，断言 runnable 一次 drain 跑完）。
  - **[r3 P2#2] FAILED resolution surface**：FAILED 现在 block 同 target 后续 mutation（round-2 P1#1 副作用），所以必须有用户出口。新增 `FailedResolution` sealed type (`Retry(freshToken?)` / `Drop`)；`OutboxRepository.resolveFailed(id, resolution)` 对称 `resolveConflict`；`observeFailed()` Flow 给 UI；DAO `observeFailedRows`。3 个新 test：retry-without-token / retry-with-fresh-token / drop。
  - **[r3 P2#3] CI schema regen diff gate**：`.github/workflows/ci.yml` Android job `Test` 步骤之后加 `Verify Room schema snapshots are committed`，用 `git status --porcelain android/app/schemas` 检测 KSP 重生的文件是否已提交；如有 diff 直接 fail 并打印 patch。保证 hand-written `9.json` placeholder 在 CI 第一次跑后必须更新提交才能再合 PR。
  - **[r3 P3#1] CHANGELOG / KDoc 旧语义清理**：PR-2g.1 CHANGELOG 块原说"4xx/5xx → Failure / 无 dispatcher 留 PENDING"，已被 round-1/2 改成"5xx/408/429/IO → RetryableFailure / 无 dispatcher → markFailed"。CHANGELOG 和 `OutboxDrainEngine` KDoc 同步更新。

- **PR-2g.1 codex round-2 fix**（PR-2g.1 codex 复审 4 个 finding 收尾）：
  - **[r2 P1#1] same-target serial 扩到 CONFLICT/FAILED**：原来 `isTargetBusy` 只查 IN_FLIGHT；CONFLICT 未处理 / FAILED 未重试的 row 不阻塞同 target 后续 PENDING，导致后续 mutation 会越过未决 conflict 自己跑。新增 DAO `hasUnresolvedRowForTarget(target, in_flight, conflict, failed)`；`dequeueNextRunnable` 改用此 method。新增两个 contract test：CONFLICT row 阻塞 PENDING 同 target / FAILED row 阻塞 PENDING 同 target。
  - **[r2 P1#2] CancellationException 不再被吞**：engine 把 `runCatching` 拆成 `try / catch (e: CancellationException) → 在 NonCancellable scope 把 row 回 PENDING 然后 rethrow / catch (Throwable) → RetryableFailure`；PatchExpenseDispatcher 显式 catch CancellationException 重抛。配套：drain start 加 `recoverStaleInFlight()` 把 attemptedAt 超过 5 分钟的 IN_FLIGHT 行扫回 PENDING（worker cancel 后死锁 IN_FLIGHT 状态的兜底）。新增 contract test：CancellationException propagate + row 回 PENDING / stale IN_FLIGHT 被 sweep 后下次 drain 跑通。
  - **[r2 P1#3] payload 反序列化错走 terminal Failure**：PatchExpenseDispatcher 把 `payloadAdapter.fromJson(...)` 移到 try 内，捕 JsonDataException / JsonEncodingException → `DispatchResult.Failure`（terminal，非 retryable）。避免 payload shape 不兼容导致无限自动 retry。
  - **[r2 P2#4] entity defaultValue 对齐**：`PendingMutationEntity.retryCount` 加 `@ColumnInfo(defaultValue = "0")` 与 `Migration8To9` 的 SQL `DEFAULT 0` 对齐，避免 Room 启动时 schema-validator 抛 "default mismatch"。9.json 的 createSql 同步加 `DEFAULT 0`。

- **PR-2g.1 codex review fix**（同时落地的 5 个 finding，PR-2g 系列契约修正）：
  - **[P1#1] outbox 同 target 串行 + Success 携 server 新 token**：`dequeueNextRunnable` 按 targetId 去重（同 target 一个 drain 只取最早一条）；`DispatchResult.Success` 改成 `data class Success(newUpdatedAt: String? = null)`；engine markDone 后 `cascadeFreshToken(targetId, newToken)` 把同 target 后续 PENDING 行的 token 改写为 server 返回的新 `updated_at`，避免链式 mutation 自己撞 fake-409；`PatchExpenseDispatcher` 解 `response.updatedAt` 回传。新 DAO method `cascadeFreshTokenForTarget`。
  - **[P1#2] markInFlight atomic claim**：DAO `markInFlight` 改为 `markInFlightIfPending` 加 `WHERE status = pending` predicate；`OutboxRepository.tryClaim()` 返回 Boolean；engine `if (!outbox.tryClaim(row.id)) raced++`，跳过 dispatcher 调用。两个 worker 并发 drain 不会 double-dispatch 同一行。
  - **[P1#3] transient failure 不退出 drain**：新增 `DispatchResult.RetryableFailure(message)`；engine retryable → `outbox.markRetryable()` 保留 PENDING 让下次 drain 取；`PatchExpenseDispatcher` 把 5xx / 408 / 429 / `IOException` 映射为 RetryableFailure；4xx terminal + 4xx validation + Discarded 不变。
  - **[P2#4] Room 9.json schema snapshot 提交**：手写 `pending_mutations` entity + 3 indices + setupQueries；`identityHash` 用 placeholder `0000…`（CI ksp build 时自动覆盖为 canonical hash），文件加 `_note` 解释。Reviewer 可看 schema diff。
  - **[P2#5] unknown row 不再阻塞 drain**：engine 遇 no-dispatcher / Unknown type → `markFailed("no_dispatcher_registered:<wireType>")`；row 离开 PENDING 队列，未来 UI 可让 user 手动重试/丢弃；`DrainSummary` 增加 `retryable` / `unsupported` / `raced` 计数。
  - 测试：`OutboxDrainEngineTest` 加 4 个新 case（success-cascades-token / same-target-serial-inside-drain / retryable-keeps-pending / pre-claimed-skipped），改写 dispatcherThrowing 走 RetryableFailure 路径；`OutboxRepositoryTest` 用 `tryClaim` 替代 `markInFlight`。FakePendingMutationDao 加 markInFlightIfPending / markRetryable / cascadeFreshTokenForTarget 实现。

- **PR-2g.1 Android outbox drain engine + dispatcher contract**：
  - `OutboxMutationDispatcher` interface：`val type: PendingMutationType` + `suspend dispatch(OutboxRow): DispatchResult`。每个 mutation 类型注册一个实现，drain engine 按 row.type 路由。
  - `DispatchResult` sealed type：Success / Conflict(serverMessage) / Failure(message) / Discarded(reason)。ADR-0038 契约：409 `state_conflict` → Conflict（surface 给 user 选 keep/drop）；404 / 422 / 非-state_conflict 409 → Discarded（结构差异，沉默 markDone + cleanup gc）；2xx → Success；其它 4xx/5xx + network → Failure（user 可手动重试）。
  - `OutboxDrainEngine.drainOnce()`：dequeue → mark in-flight → dispatch → status transition → 下一行。crash 安全（每行单独 commit）。无 dispatcher 注册的 row 留 PENDING（旧 Android build 拿到新 mutation type 时不丢数据）。
  - `PatchExpenseDispatcher` 作为第一个示范实现：解析 `targetId = "expense:<id>"`、deserialise payload、按 row.expectedUpdatedAt 覆盖 token field、调 `api.updateExpense`、HTTP 异常映射到 DispatchResult。其余 15 个 dispatcher 同形态独立 PR 加。
  - `OutboxDrainEngineTest`（6 tests）：success / conflict / failure / discarded / dispatcher 抛异常 → Failure / 无 dispatcher 注册的 type 跳过 PENDING 不动。
  - **不在此 PR 范围**（独立 PR）：WorkManager 接入 / mutation call site 走 outbox / conflict-banner UI / 其它 15 个 dispatcher 实例。

- **PR-2f Android offline outbox skeleton**：
  - Room 新增 `pending_mutations` 表（type / targetId / payload JSON / expectedUpdatedAt / status / retryCount / lastError / createdAt / attemptedAt / completedAt），AppDatabase v8 → v9 migration (new table only, 不动现有 entity)。
  - `PendingMutationEntity` / `PendingMutationStatus` (pending / in_flight / conflict / failed / done) / `PendingMutationType` (16 个 mutation 路由 wireValue mapping，对齐 backend v1.3 PR-2 mutate surface)。
  - `PendingMutationDao` 暴露 enqueue / status transitions / drain query (created_at ASC, 同 target_id 串行 via `isTargetBusy`) / live `observeQueueDepth` + `observeConflictRows` / cleanup `deleteResolvedBefore`。
  - `OutboxRepository` 抽象 + `ConflictResolution` sealed type (KeepMine(freshToken) / DropMine)。enqueue 是 fire-and-forget；dequeueNextRunnable 实施同 target 串行；gcCompleted 默认 7 天保留。
  - **不接入 mutation call sites** — PR-2g 接入。skeleton 单独 landable，便于 review schema migration 和 queue 语义。
  - `OutboxRepositoryTest` (8 tests) 用纯 Kotlin Fake DAO 验证 enqueue 排序 / dequeue 跳过同 target IN_FLIGHT / status transitions / KeepMine refresh token / DropMine 删除 / gcCompleted 保留窗口 / activeForTarget 过滤终态。

- **PR-2j v1.1 sediment 清账 + audit 收紧到 strict**：
  - `PATCH /api/goals/{public_id}` 加必填 `expected_updated_at`：`GoalUpdateRequest` 加字段（`extra="forbid"`）；`goal_service.update_goal` 改用 `claim_row_with_token` + `extra_where=(Goal.status=='active')`；rowcount=0 分支为 archived → 409 `invalid_request`，else → 409 `state_conflict`。Android `GoalUpdateRequestDto` / `GoalUpdate` domain model 加 `expectedUpdatedAt` 必传。
  - `PATCH /api/income-plans/{public_id}` 同款：`IncomePlanUpdateRequest` 加字段；service 用 `claim_row_with_token` + `extra_where=(MonthlyIncomePlan.status=='active')`；archived 仍走"请先恢复" 409 `state_conflict`。Android `IncomePlanUpdateRequestDto` / `IncomePlanPatch` mapper 加字段。
  - 剩余 4 条原 KNOWN_GAPS 移入 ALLOWLIST：`DELETE /api/income-plans/{id}` (archive lifecycle 与现有 restore POST 对称)，`PUT /api/budgets/monthly/{month}` (upsert by (tenant, month) 不是 row PATCH)，`PUT /api/dashboard/cards` (按 surface replace-all layout)，`PUT /api/me/ui-preferences` (账号级 local UI cache upsert)。
  - audit `_strict_gate_enabled()` 默认 `XPJ_AUDIT_MUTATE_TOKEN_STRICT=1`（KNOWN_GAPS 现在空集，默认 strict 不影响）；audit 数字变成 30 carry token / 108 ALLOWLIST / 0 KNOWN_GAPS。
  - 两套独立 contract test：`test_goal_optimistic_concurrency.py` / `test_income_plan_optimistic_concurrency.py`，覆盖 missing 422 / stale 409 / unknown 404 / two-session race / archived row preserved 409。

## v1.2.0 — 现金流预算 + Learning Feedback + OCR facts 单源（当前）

v1.1 主线"家庭现金流预算"与 v1.2 主线"learning-feedback + OCR facts 单源"内容均合入此 release。v1.1.0 没有单独发布 tag；版本号一次到 1.2.0。

### v1.1 主线 — 家庭现金流预算 + 自托管 AI Provider（ADR-0036）

- ADR-0036 v1.1 AI Budget Provider Privacy Boundary codify：明示 AI provider 可见的字段子集 + 本地保留 `merchant_alias_table` / `member_alias_table` / `transaction_temp_id_table` 三张映射表 + provider 不写预算 + provider 协议（[PR #92](https://github.com/zhe9898/7/pull/92)）
- BudgetAdvisor skeleton：`BudgetAdvisorProvider` Protocol + `EmptyBudgetAdvisor`（默认，纯本地）+ ADR-0036 字段 contract 编码（v1.1 PR-1，[PR #95](https://github.com/zhe9898/7/pull/95)）
- alias maps + outbound payload guard：merchant / member / transaction 三套别名映射 + 出站 payload schema 校验（ADR-0036 confirmation #1 & #2，v1.1 PR-2，[PR #102](https://github.com/zhe9898/7/pull/102)）
- `OpenAiCompatBudgetAdvisor`：真实 HTTP transport（local LLM + 云端 API 一套协议，`base_url` / `api_key` / `model` 三 env 区分）+ fail-closed semantics（v1.1 PR-3，[PR #103](https://github.com/zhe9898/7/pull/103)）
- 冷启动预算基线：50/30/20 + BLS 2024 anchor（v1.1 PR-4，[PR #104](https://github.com/zhe9898/7/pull/104)）
- 个人 P50/P75 + default-personal blend + discretionary formula：本地确定性预算公式（v1.1 PR-5，[PR #105](https://github.com/zhe9898/7/pull/105)）
- `monthly_income_plan` model + `income_plan_service` CRUD：收入计划数据模型（v1.1 PR-6，[PR #106](https://github.com/zhe9898/7/pull/106)）
- `/api/income-plans` CRUD routes + `/api/budget/discretionary` endpoint（v1.1 PR-7，[PR #107](https://github.com/zhe9898/7/pull/107)）
- `POST /api/budget/advise`：anonymising builder（按 ADR-0036 脱敏边界）+ provider integration（v1.1 PR-8，[PR #108](https://github.com/zhe9898/7/pull/108)）
- `/web` income-plans CRUD + `/web` budget-advise page（v1.1 PR-9，[PR #110](https://github.com/zhe9898/7/pull/110)）
- Android income plan vertical slice：DTO / repo / VM / screen + tests（v1.1 PR-10，[PR #111](https://github.com/zhe9898/7/pull/111)）+ `IncomePlanScreen` 接入 Settings 导航（[PR #112](https://github.com/zhe9898/7/pull/112)）
- v1.0 rollback CLI fix：PowerShell 5.1 下 `File.Replace` null backup arg 崩溃（[PR #91](https://github.com/zhe9898/7/pull/91)）

### v1.2 主线 — Learning Feedback Dual Tables（ADR-0037）

- Learning Feedback 三张 append-only 表（ADR-0037）：`algorithm_decisions`（决策事实 append-only，治理状态可流转 active/superseded/withdrawn）/ `ledger_learning_events`（用户反馈 append-only）/ `ocr_facts`（OCR 抽取事实 append-only，与 expenses 1:N）；tenant_id 强制隔离；retention_days + `cleanup_expired_learning_tables`
- 算法版本回滚：`withdraw_algorithm_version` 把整个 `(decision_type, algorithm_version)` 翻成 `withdrawn`；tenant 隔离
- Algorithm registry：`CATEGORY_SUGGESTION` / `DUPLICATE_CANDIDATE` / `BUDGET_SUGGESTION` 三类决策收拢到 `learning_service._algorithm_registry`，service 端 `ALGORITHM_VERSION` 从 registry 取
- Learning service ops 收口：`signal_hash` 信号幂等键、cleanup 接调度入口、lifecycle closing、retention split（决策 / 反馈 / OCR 各自 retention）、scheduler、manual dismiss、accept 路径关单（[PR #124](https://github.com/zhe9898/7/pull/124)）
- `_count_recent_rejects` 反馈降权：分类建议 / 重复评分在 N 天内被 reject 后自动降权
- Learning facts 与 advisor governance 打通：v1.1 budget advisor 读 v1.2 learning facts 做 personalisation
- Monthly report service / insight radar service：月度回顾 + 订阅雷达骨架（learning-feedback consumer）

### v1.2 主线 — OCR facts 单源迁移（5/5 步骤）

- Step 1: `latest_for_expense` + `read_ocr_text` 单源 helper（[PR #125](https://github.com/zhe9898/7/pull/125)）
- Step 2: rule classifiers 改走 `read_ocr_text`（[PR #126](https://github.com/zhe9898/7/pull/126)）
- Step 3: backfill `expense.raw_text` → `ocr_facts.raw_text`，兼容 pre-alembic（[PR #127](https://github.com/zhe9898/7/pull/127)）
- Step 4: read 路径 drop `expense.raw_text` fallback（[PR #128](https://github.com/zhe9898/7/pull/128)）
- Step 5: 业务逻辑彻底不再读 `raw_text`（[PR #129](https://github.com/zhe9898/7/pull/129)）
- OCR retry 行为修复：空 OCR retry 不再覆盖已有有意义文本
- Fact-backed OCR enforce：`/api/expenses/{id}/recognize-text` 强制 fact-backed；`OCR_PROVIDER=empty` 下 retry 返回 503 `ocr_not_configured` contract（smoke 适配 [PR #131](https://github.com/zhe9898/7/pull/131)）
- Maintenance scope 修复：`learning-status` / `cleanup-learning` 收到当前 admin 的 tenant

### 工程化 / 安全 / 测试

- Service 文件按职责拆包（>500L 模块）：6 个 service 模块拆 sub-packages（[PR #94](https://github.com/zhe9898/7/pull/94)）+ `_migrations.py` 985L 与 `_validate.py` 648L 拆 per-table sub-packages（[PR #93](https://github.com/zhe9898/7/pull/93)）
- 大模块按职责拆分：`web_expense_edit.py` 按 resource 拆（[PR #115](https://github.com/zhe9898/7/pull/115)）/ `web.css` 497L 按 feature 拆（[PR #117](https://github.com/zhe9898/7/pull/117)）/ Android `SettingsViewModel` 542L 按 area 拆 4 个 ViewModel（[PR #123](https://github.com/zhe9898/7/pull/123)）/ Android Repository 接口抽取 + 1835L binding test 拆分（[PR #121](https://github.com/zhe9898/7/pull/121)）/ Android `ExpenseDto.kt` + `ApiDtoContractTest.kt` 按 domain 拆（[PR #113](https://github.com/zhe9898/7/pull/113)）
- 测试按路径 / 流程 / 实体拆：`test_database_migration.py`（10 文件，[PR #114](https://github.com/zhe9898/7/pull/114)）/ `test_expenses.py`（9 文件，[PR #116](https://github.com/zhe9898/7/pull/116)）/ `test_csv_import_batches.py`（[PR #118](https://github.com/zhe9898/7/pull/118)）/ `test_alpha3_engine.py`（[PR #119](https://github.com/zhe9898/7/pull/119)）/ `test_web_app.py`（[PR #120](https://github.com/zhe9898/7/pull/120)）/ `LedgerRepositoryTest.kt`（[PR #122](https://github.com/zhe9898/7/pull/122)）
- 安全硬化：公网访问 + maintenance gates 加固、security hardening loop 收口、CodeQL 安全发现修复、CodeQL Android 分析 workflow

## v1.0.0 — 数据能力 + 三端收口 + PWA 公网层

- 商品级小票 line items：`ExpenseItem.kind` 枚举 + `items_sum_status`、OCR 折扣 / 税 / 服务费识别、`/web` 与 Android detail kind 分组与 mismatch banner（ADR-0035）
- 家庭账本拆账邀请：跨账本邀请双 DTO 分桶、账本可见性 + 幂等 UNIQUE、`/web` 与 Android 收件箱 / 已发送 UI（ADR-0029）
- 后台任务执行模型：单进程 ThreadPoolExecutor + orphan recovery + 进度 / 取消，`/web` 任务页 + Android 任务 UI（ADR-0030）
- v0.9 → v1.0 数据迁移协议：`app_meta` + schema_version lock + 切换前强制 snapshot + 30 天 rollback CLI（ADR-0031）
- `/web` 公网层硬化：Public Web Beta 双模式（loopback + public）、`__Host-session` cookie + pairing-code 启动、Cloudflare Tunnel allowlist + WAF + Access、`/static/owner` defense-in-depth、`TicketboxBoundaryCheck` 日检（ADR-0028）
- `/web` PWA install shell：manifest + service worker + meta 标签（Issue #20）
- 后端权威 FX：唯一汇率权威 + ECB 参考 + 缺率返回 pending（ADR-0027）
- 工程化收口：服务图 cycle 清零 + audit 入 CI 门禁、`release_audit` 自动 discover `_audit_*.py`、file-backed SQLite test lane、ruff C901 复杂度门禁、`X-Request-Id` + 错误体 request_id、GET retry 指数退避 + jitter、CSV import 状态机收口
- Android settings 三屏 ViewModel refactor（Repository-injected → 标准 MVI VM）
- 公网边界 P0/P1 回归：上传 / owner / uploads 探针修正、`/u/<upload_key>` Referer/Origin 日志脱敏、非 loopback `XPJ_EXTRA_LOOPBACK_HOSTS` 拒绝、非 loopback `PUBLIC_BASE_URL` 强制 https

## v0.9.0a1 — Reports / Goals / Chart UX

- 后端 Reports、Goals、Dashboard 卡片配置 API
- Android 统计页接入 Vico 图表，Goals 和 Dashboard 卡片设置
- /web Reports 接入自托管 ECharts，保留无 JS 回退
- 三端设计 token 体系（paper/mono/midnight）
- /owner 跟随三端设计 token 视觉收口

## v0.8 — Budget / 月度可花

- 服务端月度预算、弹性预算、分类预算
- "本月可花"卡片：Android 首页 + /web Dashboard
- 共享预算（仅共享账本）和预算排除分类
- 三端 Dashboard UI/UX 基线统一

## v0.6-v0.7 — Recurring + Rules + Tags + Merchant

- 固定支出正式化（recurring_items 表 + 状态机）
- 通知草稿幂等、通知偏好开关
- 商家别名、标签多对多、规则增强
- dry-run + 审计 + 回滚
- 分类组管理和性能索引

## v0.5 — Household 权限硬化

- owner/member/viewer 角色模型全链路强约束
- 成员审计、owner 转让、viewer 写保护
- 三端角色词统一（拥有者/成员/只读）
- 邀请安全（防误绑定、一次性明文码）

## v0.4 — 多账本 + 三端架构 + Smart Ledger Engine + 家庭账本

- v0.4-alpha1: 多账本地基（ledger_id 隔离、Room v4）
- v0.4-alpha2: 三端信息架构（Android 生活流 / /web 桌面流 / /owner 管理流）
- v0.4-alpha3: Smart Ledger Engine（报表、数据质量、Rules、Recurring 候选、Review Workflow）
- v0.4-beta1: 家庭账本地基（邀请、权限、隐私不变量）

## v0.3 — 身份系统重做

- Account / Ledger / Device / AuthToken / UploadLink / PairingCode 六表
- Owner Console + /web 网页版 + iPhone UploadLink
- 公网边界 35/35 验收
- identity_schema=v0.3 确立（至今不变）
