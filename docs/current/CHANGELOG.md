# Changelog

## Upgrade Notes

- ADR-0038 undo (first slice — merchant_alias): `DELETE /api/merchants/aliases/{id}`
  now SOFT-deletes (sets `deleted_at`). The alias is hidden from every read but
  recoverable via `POST /api/merchants/aliases/{id}/undo` until cleanup purges
  it past a 5-minute retention window (`purge_expired_soft_deleted_merchant_aliases`).
  Undo appends a `ledger_audit_logs` `action='undo'` row — that audit log gained
  generic, nullable `resource_type` / `resource_public_id` columns so it can record
  resource-level actions alongside the family/membership rows. The
  `(tenant_id, alias_key)` unique constraint is intentionally kept, so a
  soft-deleted key stays reserved during its undo window (recreating it returns
  409 until undo or purge, which also guarantees undo never resurrects a
  duplicate). Migrations are additive only (one nullable column per table); no
  table rebuild. The undo affordance is wired on both the `/web` merchants page
  (5s 撤销 banner) and the Android merchant-alias screen (5s 撤销 bar, shown only
  after a synced delete).

- ADR-0038 undo (second slice — category_rules): `DELETE /api/rules/categories/{id}`
  now SOFT-deletes (sets `deleted_at`) instead of hard-deleting; the rule is
  hidden from every read — the classifier matcher, the rule list/get, and the
  apply/preview/conflict engines all filter `deleted_at IS NULL` — but
  recoverable via `POST /api/rules/categories/{id}/undo` until the periodic
  purge sweeps it past the 5-minute retention window. Undo clears `deleted_at`
  and appends a `ledger_audit_logs` `action='undo'` row. Unlike merchant_alias
  there is no unique constraint, so a recreated rule never conflicts and undo
  never resurrects a duplicate. Additive migration only (one nullable column +
  composite index); the periodic purge scheduler now sweeps category_rules too.
  The `/web` rules page now renders a 5s 撤销 banner after a delete (POSTs to
  `/web/rules/{id}/undo`), mirroring the merchant page; the Android undo
  affordance follows in a later slice.

- ADR-0038 undo cleanup now has a periodic purge scheduler. Opt in with
  `SOFT_DELETE_PURGE_AUTO_ENABLED=true` to auto-purge soft-deleted rows past
  their retention window every ~30 min (off by default, like the other cleanup
  schedulers). Soft-deleted rows are hidden from every read regardless, so this
  only bounds storage lag, never the undo window.

- ADR-0036 AI advisor (widened): the outbound payload now also carries a
  **coarse fixed/recurring-commitment aggregate** — `recurring_total_monthly_cents`
  and `recurring_active_count` (two scalars). Recurring items are merchant-keyed
  (PII), so only the aggregate magnitude crosses — never per-merchant rows,
  amounts, or names; paused/archived items are excluded. The outbound guard
  fail-closes on either scalar that is not a non-negative int.

- ADR-0036 AI advisor (widened): the outbound payload now also carries
  **planned income** — `income_plan[]` with a generalised `source_type`,
  `amount_cents`, and `pay_day` — so the advisor can reason about cash flow,
  not just spend. `source_type` is free text in storage, so the builder
  generalises it to a PII-free allowlist (unknown → `other`) and the outbound
  guard fail-closes on anything outside it; the free-text income `label` is
  never sent. Merchant/member aliases stay out.

- `/web/reports` now renders its three ECharts (spending trend / category
  month-over-month / merchant ranking) via `reports.js` from a server-injected
  `#reports-overview-data` JSON blob, plus a "导出 PNG" trend snapshot. Activates
  ADR-0026's chart layer (the page previously shipped only a partial chart set,
  driven by the older per-container scripts); the backend report contract is
  unchanged.

- AI budget-advisor live provider payload is now explicitly limited to
  month/home-currency, category aggregates, and historical category baselines.
  Merchant/member aliases and fixed/recurring summaries are kept out of the
  outbound provider envelope unless a future ADR/code/test change widens it
  (income plans were since widened in — see the ADR-0036 entry above).
  `BUDGET_ADVISOR_API_KEY` is also no longer trimmed during config loading:
  leading/trailing spaces or embedded whitespace are rejected as invalid config
  instead of being silently corrected.
  Existing ledger categories are normalized to the default category catalog
  before provider calls, and the outbound guard rejects any programmatic
  advisor payload whose category is outside `DEFAULT_CATEGORIES`.

- `release_audit.py` now includes explicit cloud/multi-instance hardening
  gates for advisor quota reservation, UploadLink quota/legacy expiry spread,
  scheduler leases, auth-token rotation grace, OCR/CSV scaling contracts,
  perceptual duplicate detection, structured tag relations, Android outbox
  invariants, fresh schema metadata, advisor provider config validation,
  bill-split total-cap serialization, advisor failure reason codes, and
  thumbnail cleanup rollback.

- Legacy UploadLink rows with missing `expires_at` are now backfilled to
  `UPLOAD_LINK_TTL_DAYS + (id % UPLOAD_LINK_LEGACY_EXPIRY_SPREAD_DAYS)`.
  The default spread is 30 days, so old links do not all expire on the same
  day after a cloud or multi-user upgrade. Operators can raise
  `UPLOAD_LINK_LEGACY_EXPIRY_SPREAD_DAYS` before migration for a wider rollout.

- Public UploadLink daily byte limits are now reserved in the database before
  the request body is read. Concurrent workers share the same quota row, failed
  uploads release their reservation, and a process crash fails closed by keeping
  the reserved bytes for that UTC day.

- Android outbox rows now persist `serverUrl` and `ledgerId`, and drain,
  status, conflict, failed, stale-recovery, cascade, and active-target reads are
  all scoped to that binding. Server/ledger switches no longer need to trade
  correctness for dropping the whole offline queue; explicit sign-out and debug
  rebind paths still call `clearAll()` to remove private local state.

- In-process schedulers now claim a short database lease in `app_meta` before
  running scheduled FX sync or cleanup jobs, so multi-worker/cloud deployments
  do not duplicate those jobs merely because each worker started a daemon
  thread.

- Background-task startup recovery keeps the existing single-process default,
  but cloud/multi-worker deployments can set
  `BACKGROUND_TASK_ORPHAN_GRACE_SECONDS` so a newly started worker does not
  immediately fail fresh `queued`/`running` work owned by another worker.

- Device pairing failures (expired code, already-used code, invalid code) now
  all return `invalid_pairing_code` (HTTP 401). The previous distinct
  `pairing_code_expired` (410) / `pairing_code_used` (409) codes are removed so
  the endpoint no longer reveals whether a given code existed. The user-facing
  message ("绑定码无效，请重新生成") still tells the user to request a fresh code.

- `LOCAL_LLM_MAX_CONCURRENT` now defaults to `2` to allow a little OCR
  throughput overlap. A single-GPU / single-stream local vision model should
  set `LOCAL_LLM_MAX_CONCURRENT=1` to avoid VRAM contention; the slot queue and
  `LOCAL_LLM_QUEUE_TIMEOUT_SECONDS` still bound how long callers wait.

- Perceptual-hash duplicate detection now scans at most
  `DUPLICATE_PHASH_SCAN_LIMIT` (default 500) of the most-recent image-bearing
  expenses instead of the whole ledger, so uploads stay fast on large ledgers.
  Raise it to widen the duplicate-detection window at the cost of upload latency.

- `GET /api/tasks` and task get/cancel are now scoped to the caller's active
  ledger as well as their account, so a multi-ledger user no longer sees or
  cancels tasks they started under a different ledger binding.

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

- **PR-2g.9 Android acknowledge-items-mismatch（原小票如此）过 outbox**：
  - 新增 `AcknowledgeItemsMismatchDispatcher`（POST `/api/expenses/{id}/items/acknowledge-mismatch`），token-only，target `expense:<id>`，复用 `expenseStateTokenAdapter`。**与 confirm/reject 的差异**：ack 的 response 是 items payload，**不含父 expense 的新 `updated_at`** → `Success(newUpdatedAt = null)` 不级联。chain 到同-target 后续行可能 409 → CONFLICT row 用户处理（accepted edge，items 端点 shape 喂不了 cascade）。
  - **新 outcome 类型 `ItemsAckOutcome`**（Synced/Queued 带 `ExpenseItems` 非 `Expense`，平行定义在 `ExpenseDetailRepository.kt`）。`acknowledgeItemsMismatchAllowingOffline(expense, currentItems)`：取**当前 items** 才能做离线乐观投影（`itemsSumStatus → mismatch_acknowledged`，角标立即清）；direct 2xx → Synced（server items）；IOException → Queued + enqueue。复用 `core.enqueueStateTransition`（传 expense 拿 id+token）。保留 `canModifyLedger` 只读门槛。
  - VM `ExpenseEditViewModel.acknowledgeItemsMismatch` 改接 + 分支：Synced → 跟 PR-2e 一样**二次 `fetchExpense`** 刷新父 token（ack 服务端 bump 了 `updated_at` 但响应没带）+ "已确认原小票如此。"；Queued → **不 fetch**（离线），直接显示乐观 items + "已离线确认，联网后同步"。guard 从只看 token 改成 expense + currentItems 都要非空。
  - `AppContainer` 注册（现共 10 dispatcher）。acknowledge **不在 `PendingReviewActions` 接口上**（走 `ExpenseDetailRepository` → `ExpenseRepository` concrete）→ 不动任何 fake、不动 `PendingViewModel`。
  - 3 个新 contract test（`ExpensePendingRepositoryOutboxFallbackTest`：ack direct 2xx → Synced / IOException → Queued + `mismatch_acknowledged` 投影 + 不含 token / 409 → 失败）。stub 加 `acknowledgeExpenseItemsMismatch` override（返 `ExpenseItemsResponseDto`，与 ApiResult 不同类型故用单独 `acknowledgeException` 开关）。
  - **不在此 PR**：`ReplaceItems`+`ReplaceSplits`+`ConfirmedBatchUpdate`（需先补 Android UI）。

- **PR-2g.8 Android mark-not-duplicate + retry-OCR 过 outbox**：
  - 新增 `MarkNotDuplicateDispatcher`（POST `/api/expenses/{id}/mark-not-duplicate`）+ `RetryOcrDispatcher`（POST `/api/expenses/{id}/ocr/retry`），token-only，target `expense:<id>`，形态与 PR-2g.7 confirm/reject 一致，复用同一个 `expenseStateTokenAdapter`。
  - **helper 提取到 core**：PR-2g.7 的 `enqueueStateTransition`（session-race guard + token 占位 + enqueue）从 `ExpensePendingRepository` 私有方法上提到 `ExpenseRepositoryCore.enqueueStateTransition`，因为 retry-OCR 在 `ExpenseDetailRepository`、mark-not-dup 在 `ExpensePendingRepository`，两个 repo 都要用。`type = PendingMutationType.X` 字面量留在各 call site（confirm/reject/markNotDup 在 pending repo，retryOcr 在 detail repo），outbox-coverage audit 仍识别到 enqueue。confirm/reject 改调 `core.enqueueStateTransition`，行为不变。
  - `ExpensePendingRepository.markNotDuplicateAllowingOffline(expense)`：IOException → Queued，乐观投影把 `duplicateStatus` 翻 `none`（清掉疑似重复角标），**账单留在 pending 列表**（mark-not-dup 是"保留"不是移除，用 `afterUpdated` 非 `afterRemoved`）。`PendingReviewActions` 加该接口方法。
  - `ExpenseDetailRepository.retryOcrAllowingOffline(expense)`：IOException → Queued，**乐观投影 = expense 原样不变**（OCR 在服务端跑，离线没东西可投影），UI 只显示"已离线，联网后重试识别"。挂在 `ExpenseRepository`（concrete，非接口——retryOcr 不在 `PendingReviewActions` 上）。
  - VM 改 3 个 call site：`PendingViewModel.markNotDuplicate`（Synced "已保留这条账单" / Queued "已离线保留，联网后同步"）、`ExpenseEditViewModel.markNotDuplicate`（同上）、`ExpenseEditViewModel.retryOcr`（Synced "识别已重试" / Queued "已离线，联网后重试识别"）。
  - `AppContainer`：注册 2 个新 dispatcher（现共 9：+ MarkNotDuplicate / RetryOcr）。adapter 已是 PR-2g.7 共享的 `expenseStateTokenAdapter`，无新增。
  - 6 个新 contract test（`ExpensePendingRepositoryOutboxFallbackTest`：markNotDup direct 2xx / IOException → Queued + `none` 投影 + 不含 token；retryOcr direct 2xx / IOException → Queued 原样）+ 1 个 VM test（离线 markNotDup 留列表 + 离线文案）。fake 不动 ApiService（端点早存在），两个 `PendingReviewActions` fake 加 `markNotDuplicateAllowingOffline`。
  - **不在此 PR**：`acknowledgeItemsMismatch`（PR-2g.9，返 `ExpenseItems` 非 Expense，需新 outcome 类型）/ `ReplaceItems`+`ReplaceSplits`+`ConfirmedBatchUpdate`（需先补 Android UI）。

- **PR-2g.7 Android confirm / reject expense 状态机 POST 过 outbox**：
  - 新增 `ConfirmExpenseDispatcher`（POST `/api/expenses/{id}/confirm`）+ `RejectExpenseDispatcher`（POST `/api/expenses/{id}/reject`），target `expense:<id>`，token-only body（`ExpenseStateTokenRequest`），形态镜像 PR-2g.5 `DeleteMerchantAliasDispatcher`。confirm/reject 的 response 是完整 Expense，所以 `Success(newUpdatedAt = response.updatedAt)` 级联同-target PENDING 行（离线 edit→confirm 链不自我假冲突）。
  - `ExpensePendingRepository` 新增 `confirmExpenseAllowingOffline(expense)` + `rejectExpenseAllowingOffline(expense)` 返 `Result<ExpenseStateOutcome>`（新 sealed Synced/Queued 都带 `expense`，与 `SaveOutcome` 并行定义，confirm/reject/后续 markNotDuplicate 共用）；direct `confirmExpense/rejectExpense(id, token)` 保留给链式调用方。两方法共享 `enqueueStateTransition` helper（round-13 P1 `requireStillActive` BEFORE enqueue + round-8 P3#5 token `""` 占位）。取整个 `expense`（非 id+token）因为 Queued 分支要 baseline 字段做乐观投影——同 `saveExpenseAllowingOffline` 取 baseline 的理由。
  - **只 wire 3 个真直连 call site**：`PendingViewModel.confirm`/`reject` + `ExpenseEditViewModel.reject`，按 outcome 分支文案（Synced "已确认入账"/"已删除"；Queued "已离线确认/删除，联网后同步"）。乐观投影把 `status` 翻成 `confirmed`/`rejected`，reducer `afterConfirmed`/`afterRejected` 按 id 把账单移出 pending 列表（在线/离线一致）。
  - **留直连不过 outbox（有意）**：`ExpenseEditViewModel.confirm`（链式 save→confirm，喂 `saved.updatedAt`）、`PendingViewModel.saveAmountAndConfirm`（链式 update→confirm）、`confirmReadyExpenses`（批量循环，自带 succeeded/failed 进度）——链式流必须 fail-fast，silent 队列会让后续 POST 带 stale token 链；批量循环的"queued"语义与进度模型不契合。
  - `AppContainer`：注册 2 个新 dispatcher 到 `outboxDispatchers`（现共 7 dispatcher：PatchExpense / UpdateCategoryRule / DeleteCategoryRule / DeleteMerchantAlias / UpdateMerchantAlias / ConfirmExpense / RejectExpense）；新增共享 `expenseStateTokenAdapter`（confirm/reject 同 body，一个 adapter 服两个 dispatcher + repository）。
  - 8 个新 contract test：`ExpensePendingRepositoryOutboxFallbackTest` 加 6 个（confirm direct 2xx → Synced 不入队 / IOException → Queued 入队 + confirmed 投影 + payload 不含 token / 409 → 失败 / outbox 未接 → 失败；reject direct 2xx / IOException → Queued + rejected 投影）；`PendingViewModelReviewActionsTest` 加 2 个 Queued 路径 VM test（离线 confirm/reject 仍移出列表 + 离线文案）。fake 不动 ApiService（confirm/reject 端点早存在），`FakeReviewActions` 默认把现有 `confirm/rejectResponder` 包成 `Synced` 保持在线测试零改动。
  - **范围订正**：交接合同把 9 个 forward-declared type 都标"活流"，实测只有 5 个有真 UI 触发（confirm / reject / markNotDuplicate / retryOcr / acknowledgeItemsMismatch）。`ReplaceItems` / `ReplaceSplits` / `ConfirmedBatchUpdate` 后端端点在但 Android 无 UI 入口，`RecognizeText` 后端都没端点——这几个要先补 Android UI 才能 wire（产品已确认补）。
  - **不在此 PR**：`markNotDuplicate` + `retryOcr`（PR-2g.8）/ `acknowledgeItemsMismatch`（PR-2g.9）/ `ReplaceItems`+`ReplaceSplits`+`ConfirmedBatchUpdate`（需先补 UI）。

- **PR-2g.6 Android PATCH merchant_alias 过 outbox**：
  - 新增 `UpdateMerchantAliasDispatcher`（PATCH `/api/merchants/aliases/{publicId}`，target `merchant_alias:<publicId>`），形态镜像 PR-2g.4 `UpdateCategoryRuleDispatcher` + PR-2g.5 `DeleteMerchantAliasDispatcher`。
  - `MerchantRepository` 加 `merchantAliasUpdateAdapter` 可选构造参（默认 null backward compat），新增 `updateMerchantAliasAllowingOffline(baseline, canonicalMerchant?, alias?, enabled?)` 返 `Result<MerchantAliasSaveOutcome>`（sealed Synced/Queued，与 `CategoryRuleSaveOutcome` 并行）；direct `updateMerchantAlias` 保留。
  - `MerchantAliasViewModel.toggleMerchantAlias` 切到新方法，按 outcome 分支文案（Synced "已启用/已停用"，Queued "已离线启用/停用，联网后同步"）。`MerchantAliasViewModel.updateMerchantAlias` 当前无完整编辑入口（只有 toggle），所以这次仅 wire 一个 call site。
  - **Round-13 P1 一致**：新方法上手即用 `val bound = ledgerRequestGuard.bind()` + `bound.call { ... }` + IOException catch 里 `bound.requireStillActive()` BEFORE enqueue — 不留窗口。
  - **Round-8 P3#5 一致**：enqueue 用 `request.copy(expectedUpdatedAt = "")` 占位（DTO 非空 String），dispatcher replay 时从 row.expectedUpdatedAt 覆盖填。
  - `AppContainer`：注册 `UpdateMerchantAliasDispatcher` 到 `outboxDispatchers`（现共 5 dispatcher：PatchExpense / UpdateCategoryRule / DeleteCategoryRule / DeleteMerchantAlias / UpdateMerchantAlias）；共享 `merchantAliasUpdateAdapter` 给 dispatcher 和 repository。
  - 4 个新 contract test (`MerchantRepositoryOutboxFallbackTest`)：direct 2xx → Synced 不入队 / IOException → Queued 入队 + 乐观投影 + payload 不含 token / 409 → 失败 / outbox 未接 → 失败。
  - **Pre-flight checklist** 4 项全过：caller grep（3 个 MerchantRepository ctor 站点 backward compat）/ CI symptom / KDoc/body / bypass。
  - **不在此 PR**：剩 11 个 mutation type（PR-2g.7+）/ Compose conflict banner (PR-2g.11)。

- **PR-2g.5 Android DELETE 两对：category_rule + merchant_alias 过 outbox**：
  - 新增 `DeleteCategoryRuleDispatcher`（DELETE `/api/rules/categories/{id}`，target `category_rule:<id>`）和 `DeleteMerchantAliasDispatcher`（DELETE `/api/merchants/aliases/{publicId}`，target `merchant_alias:<publicId>`）。两个 dispatcher 同形态（token-only body），HttpException 映射与 PR-2g.4 PATCH 一致；DELETE 404 → `Discarded`（"已经没了"等于意图达成）。
  - 新增 `DeleteOutcome` sealed type（共享给 Category 和 Merchant 两边 DELETE 路径）：`Synced` / `Queued`，无 payload —— DELETE 不返实体，只用来决定 UI 文案。放在 `RuleRepository.kt` top-level，`MerchantRepository.kt` 直接 import。
  - `RuleRepository.deleteCategoryRuleAllowingOffline(rule)` + `MerchantRepository.deleteMerchantAliasAllowingOffline(alias)`：IOException → enqueue + `Queued`；HttpException 一律 fail。两个 Repository 都加可选 `outbox` + `xxxDeleteAdapter` 构造参（默认 null 兼容老测试）。
  - `CategoryRulesViewModel.deleteCategoryRule` + `MerchantAliasViewModel.deleteMerchantAlias` 两个 call site 切到新方法：Synced → "已删除"；Queued → "已离线删除，联网后同步"。UI 列表本来就 filter 掉，message 是唯一差异。
  - **Round-8 P3#5 一致**：`DeleteRequest` DTO 的 `expectedUpdatedAt` 是非空 String，enqueue 时用 `request.copy(expectedUpdatedAt = "")` 占位；dispatcher replay 时从 `row.expectedUpdatedAt` 覆盖填回。
  - `AppContainer`：注册 2 个新 dispatcher 到 `outboxDispatchers`；新增 `categoryRuleDeleteAdapter` + `merchantAliasDeleteAdapter` 两个共享 adapter；分别传给对应 Repository。
  - 9 个新 contract test：`RuleRepositoryOutboxFallbackTest` 加 4 个 DELETE case（direct 2xx / IOException / 409 / outbox 未接），`MerchantRepositoryOutboxFallbackTest` 新文件 5 case（direct 2xx / IOException / 409 / 500 / outbox 未接）。
  - **Pre-flight checklist**（per `feedback_verify_fix_before_push`）：caller grep (3 个 MerchantRepository ctor 站点全部 backward compat) / fix-not-effective 对应到具体测试名 / KDoc-body 自洽 / bypass path grep 干净。
  - **不在此 PR**：`UpdateMerchantAlias` PATCH 单独走 PR-2g.6（独立 PATCH 镜像 PR-2g.4，本 PR 专注 DELETE 形态）。

- **PR-2g.4 Android PATCH category_rule 第二个 dispatcher + call site 路由**：
  - 新增 `UpdateCategoryRuleDispatcher`（target 编码 `category_rule:<id>`，对应 `PATCH /api/rules/categories/{id}`），镜像 `PatchExpenseDispatcher` 形态：HttpException 映射 (409 state_conflict → Conflict / 408+429+5xx → RetryableFailure / 404+422 → Discarded)、IOException → RetryableFailure、JsonDataException/EncodingException → terminal Failure、CancellationException 显式重抛、其它 Exception → Failure。
  - `RuleRepository`：构造器加可选 `outbox: OutboxRepository? = null` + `categoryRuleUpdateAdapter: JsonAdapter<CategoryRuleUpdateRequest>? = null`（默认 null 让 `ExpenseRepositoryRuleGovernanceTest` 等老测试零改动）；新增 `updateCategoryRuleAllowingOffline(baseline, keyword?, category?, enabled?, priority?)` 返 `Result<CategoryRuleSaveOutcome>`（sealed Synced/Queued，与 expense 路径并行定义不复用，避免 PR-2g.3 已落地的 `SaveOutcome` 改 surface）；direct `updateCategoryRule` 保留不动给现有调用方。
  - **Round-8 P3#5 一致**：enqueue 时 `request.copy(expectedUpdatedAt = "")` 把 token 清空（DTO 字段非空，用空串代替 null），dispatcher 在 replay 时用 row.expectedUpdatedAt 覆盖。
  - 乐观投影 `projectOptimisticRule`：把 user 提交的字段叠到 baseline，updatedAt 保持 pre-mutation（明示不是 server token，chain caller 也不该走这条路径）。
  - `CategoryRulesViewModel.updateCategoryRule` + `toggleCategoryRule` 两个 call site 切到新方法，按 outcome 分支文案：Synced → "分类规则已更新" / "已启用" / "已停用"；Queued → "已离线保存，联网后同步" / "已离线启用，联网后同步" / "已离线停用，联网后同步"。`deleteCategoryRule` 不在本 PR 范围（DELETE dispatcher 形态独立，PR-2g.4.2 单独做）。
  - `AppContainer`：注册 `UpdateCategoryRuleDispatcher` 到 `outboxDispatchers` 列表第 2 位；共享 `outboxMoshi` 建 `categoryRuleUpdateAdapter`，dispatcher 和 repository 共用同一 adapter 保证 roundtrip 一致。`RuleRepository` 构造时传 `outbox + categoryRuleUpdateAdapter`。
  - 8 个新 contract test (`RuleRepositoryOutboxFallbackTest`)：direct 2xx → Synced 不入队 / IOException → Queued 入队 + 乐观投影 + payload 不含 token / IOException enabled-toggle → Queued 翻转 enabled / 409 / 422 / 500 三个 HttpException 不入队 / IOException 但 outbox 未接 → 失败。
  - **不在此 PR**：DeleteCategoryRule dispatcher / 剩下 14 个 mutation 类型 / Compose conflict banner UI (PR-2g.5)。本 PR 把"第二例 dispatcher + call site"模板验稳，给后续 14 个 type 提供 cookbook 范式。

- **PR-2g.3 Android PATCH expense 第一个真过 outbox 的 call site**：
  - **API 拆两个方法（codex round-8 P2）**：`PendingReviewActions.updateExpense(id, draft, baseline): Result<Expense>` 是直调 PATCH，**任何错误**（IOException / HttpException）都 `Result.failure`，用于链式调用方（`ExpenseEditViewModel.confirm` / `PendingViewModel.saveAmountAndConfirm` 在 PATCH 后把 `saved.updatedAt` 喂给 confirm POST）—— stale token 链不能走 silent 队列。新增 `saveExpenseAllowingOffline(id, draft, baseline): Result<SaveOutcome>` 返 sealed `SaveOutcome.Synced(Expense)` / `Queued(Expense)`，给"纯保存不级联"的 call site（目前仅 `ExpenseEditViewModel.save`）；UI 按 outcome 分支显示"已保存" vs "已离线保存，联网后同步"。
  - **outbox 走 sealed result + 乐观 expense**：`saveExpenseAllowingOffline` 直 PATCH 失败时仅 IOException → `Queued(projectOptimisticExpense(baseline, draft))`（baseline.copy 把 draft 字段叠上，user 看到的是自己刚改的商家/金额）；409/422/5xx 等 HttpException 一律走 `safeCall` 失败路径；outbox 未接 / baseline 无 token → 也走失败路径。
  - **outbox row 不再重复存 token（codex round-8 P3#5）**：enqueue 时 `request.copy(expectedUpdatedAt = null)` 序列化，token 单一真源就是 outbox row 的 `expectedUpdatedAt` 字段；replay 时 `PatchExpenseDispatcher` 本来就用 row token 覆盖 request token，重复存反而是漂移风险。
  - **session 边界 clearAll（codex round-8 P1）**：outbox row 当前只携 type/targetId/payload/expectedUpdatedAt，没有 serverUrl/ledgerId，绑定切了之后旧 row 会用新 session 回放（轻则 404，重则误改无关行）。`OutboxRepository` 加 `clearAll(): Int` + DAO `@Query("DELETE FROM pending_mutations")` + `onClearAll: () -> Unit` callback（AppContainer 注入 `OutboxScheduler.cancel(appContext)`）。`LocalLedgerSessionCoordinator` ctor 加 `outbox: OutboxRepository?` 参，`cacheInvalidation == TargetLedger / AllLedgers` 时一并 `outbox?.clearAll()`。`ExpenseRepositoryCore.clearBinding()` 也调一次。AppContainer 构造顺序调整：outbox → coordinator → engine → expenseRepository。永久门槛而不是数据保留 — 把"用旧 session 误回放"换成"切绑定时丢一次队列内容"是有意识的取舍。后续 cloud-hardening pass 已把这个临时取舍升级为 `serverUrl` + `ledgerId` per-binding outbox schema；`clearAll()` 现在只保留给显式 sign-out / debug rebind 这类需要删除本地私有状态的路径。
  - **runCatching → catch Exception（codex round-8 P2#2）**：`enqueue` 内部对 `onEnqueued()` 的包装从 `runCatching` 改成 `try / catch (Exception)`，避免吞 JVM 级 Error（与 round-5 catch Throwable→Exception 同原则）；`clearAll` 内部的 `onClearAll()` 也走同样形态。
  - `AppContainer`：共享一个 Moshi 实例 + `patchExpenseAdapter` 给 `PatchExpenseDispatcher` AND `ExpenseRepository`（toJson/fromJson 同一个 adapter 保证 roundtrip 一致）。
  - 11 个新 contract test (`ExpensePendingRepositoryOutboxFallbackTest`)：direct 2xx → Synced 不入队 / IOException → Queued 入队 + optimistic expense + payload 不含 token / 409 / 422 / 5xx 三个 HttpException 不入队 / IOException 但 outbox 未接 → 失败 / `updateExpense` 直调（链式）IOException 必失败 + 不入队 / `onEnqueued` 抛异常 → enqueue 仍成功 / `clearAll` → 全删 + `onClearAll` 触发 / `onClearAll` 抛异常 → clearAll 仍成功。
  - **不在此 PR**（独立 PR）：剩下 15 个 mutation call site（PR-2g.3 follow-ups）+ 15 个 dispatcher（PR-2g.4 系列）+ Compose conflict / failed-resolution banner（PR-2g.5）+ 未来 Room v10 加 ledger_id 列让 outbox per-binding 过滤而不是 wipe。

- **PR-2g.2 Android WorkManager scheduler 接入**：
  - `androidx.work:work-runtime` 2.11.2 加进 version catalog + app `build.gradle.kts`（`work-runtime-ktx` 从 2.9.0 起已经清空，CoroutineWorker 现在直接在主 artifact 里）。
  - `OutboxDrainWorker(CoroutineWorker)`：`doWork()` 通过 `applicationContext as TicketboxApplication` 拿 `AppContainer.outboxDrainEngine`，调一次 `drainOnce()`，把 `DrainSummary` 翻译成 `Result.success() / Result.retry()`。映射策略：idle / 任何 row 前进（done / conflict / failure / discarded / unsupported）→ SUCCESS；全 retryable → RETRY（让 WorkManager 走 exponential backoff）；全 raced → SUCCESS（赢的那个 drain 在负责）；engine 抛非 cancellation 异常 → RETRY；CancellationException → 直接重抛让 WorkManager 不把它算成 backoff cycle。
  - 选择 runtime container lookup 而不是 custom WorkerFactory：app 用手写 DI (`AppContainer`)，第一次只有一个 Worker，引入 WorkerFactory + Initialize/Provide pattern 过早；第二个 Worker 出现时再升级。
  - `OutboxScheduler` object：`PERIODIC_WORK_NAME` / `ONE_TIME_WORK_NAME` 命名 unique work，两个入口：`ensurePeriodic(ctx)` 起 15 分钟 + `NetworkType.CONNECTED` constraint 的 `PeriodicWorkRequest`（UPDATE policy 让 app 升级时换新 interval/constraint 不留 stale schedule）；`enqueueOnce(ctx)` 起单次 `OneTimeWorkRequest`（KEEP policy 让 burst 调用幂等）。`BackoffPolicy.EXPONENTIAL` + 30s 起步。`cancel(ctx)` 给 sign-out 流程留口子。NetworkType.CONNECTED constraint 顺手就吃下了 ADR-0038 的 "drain on connectivity-up" 契约——OS 在离线时间窗里把 tick buffer 住，网络回来立刻 fire。
  - `AppContainer`：新增 `outboxRepository` + `outboxDrainEngine` 属性；engine 现注册一个 dispatcher `PatchExpenseDispatcher`（PR-2g 的 reference 实现，剩下 15 个 type 之后 PR 一个一个加，list 末尾 append 即可）。dispatcher 用 `() -> ApiService` provider lambda 而不是构造时捕获 ApiService 实例，避免账本切换后 dispatcher 还用旧 session 401 永远。AppContainer 内单独建一个 Moshi 用来给 dispatcher payload adapter（不复用 ApiClient 内部那个，私有作用域；adapter 都 immutable 没成本）。
  - `TicketboxApplication.onCreate`：`OutboxScheduler.ensurePeriodic(this)` + `enqueueOnce(this)` 一并启动，避免冷启动后到第一个 periodic tick 之间有最多 15 分钟空窗，期间用户在上次离线攒下的 row 没人处理。
  - `OutboxDrainWorkerTest`（11 个 case）：用纯 JVM lambda 注入而不是 fake engine（engine 是 final by design，没多态责任），覆盖 idle / all-retryable / mixed-with-done / conflict-only / failure-only / discarded-only / unsupported-only / all-raced / engine-throws-non-cancel / engine-throws-cancellation / 真实 summary roundtrip 11 个分类分支。把 `runDrain` + `classify` 提取成 internal companion 函数避开 Robolectric。
  - PR-2g.2 后续 fix：`runDrain` 第一版在 catch 里直接 `Log.w(TAG, ...)`，CI test 跑 pure-JVM 单测时 `android.util.Log` 是 unmocked stub，调用就抛 "Method w in android.util.Log not mocked"，masquerading as test 自己 throw 的 RuntimeException。改成 `runDrain(logWarning: (String, Throwable) -> Unit = { _, _ -> }, drain: ...)`，doWork 注入真实 `Log.w`，test 用默认 no-op。边界：runDrain = pure policy，doWork = Android glue。不开 `returnDefaultValues=true`（不为单一 Log.w 把全局 framework misuse 探测能力关掉）。
  - **不在此 PR**（独立 PR）：16 个 mutation call site 真正 route 到 outbox（PR-2g.3）；剩下 15 个 dispatcher（PR-2g.4 系列）；Compose conflict / failed-resolution banner（PR-2g.5）。这一 PR 只把"drain 怎么被 OS 触发"和"engine 怎么进 AppContainer"两件事接好。

- **PR-2g.1 codex round-6 fix**（PR-2g.1 codex 六审 1 个 P1 + 1 个 P2 + 2 个 P3 收尾）：
  - **[r6 P1] CI schema gate 路径 bug**：round-3 加的 schema gate 在 `working-directory: android` 下跑 `git status --porcelain android/app/schemas` —— 实际查的是 `android/android/app/schemas`，目录不存在 → 输出为空 → gate 总是假通过。即使 KSP 重写了 9.json 也检测不到。修法：gate step 显式 `working-directory: .`，从 repo root 跑 git。这把 round-3 引入但失效的"必须提交 canonical schema"门槛真正激活；本轮第一次 CI run 预期会触发 schema diff 失败，把 KSP 重生的 9.json patch 打到 log，提交后再过。
  - **[r6 P2] outbox timestamps 改成固定宽度 ISO**：`OutboxRepository.ISO` 从 `DateTimeFormatter.ISO_INSTANT` 改成 `ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSS'Z'").withZone(UTC)`。`ISO_INSTANT` 在秒整数边界省略小数秒，造成 `2026-05-04T12:00:00.001Z`（字典序）`<` `2026-05-04T12:00:00Z`（晚 1ms 反而排前），影响 `ORDER BY createdAt` 因果序 + `recoverStaleInFlight` cutoff 比较。固定 24 字符宽度后字典序与时间序一致。
  - **[r6 P3#1] OutboxMutationDispatcher KDoc 实现对齐**：接口顶部还写"any other 4xx/5xx → Failure"，与 round-1 起 5xx/408/429/IO → RetryableFailure 的实现脱节。改写成 4 类 result 准确描述：Success/Conflict/RetryableFailure/Failure/Discarded。后续 dispatcher 实现者按此条件分支。
  - **[r6 P3#2] catch Exception 不 catch Throwable**：（与 round-5 同。本轮跟 round-5 一起推上。）
  - **[r6 后续] schema gate 真激活 + 强制 KSP 重生**：r6 P1 修路径之后跑了一遍 CI 发现 gate 仍假通过 — 根因是 Room KSP 在 `room.incremental=true` 且 schemaLocation 文件已存在时不会主动覆盖（即使内容是手写 placeholder identityHash）。三处加固：(1) 新增"Force regenerate latest Room schema" step，gradle test 前显式 `rm` `schemas/<DB>/N.json`（最高版本，由 `ls | sort -n | tail -1` 动态发现），KSP 必须重写；(2) gate 步骤的 diff print 去掉 `head -200` 截断（schema JSON ~300 行），并把 untracked file 也 cat 出来（`git diff` 默认不带未跟踪文件）；(3) 加 `actions/upload-artifact` 把 schemas 目录传上来（`if: always()` 不管成败都传），canonical baseline 可下载回来提交。永久 gate：从此每次 CI 都从零重生 latest schema 跟 HEAD 对账，发现 entity / hand-written schema 漂移立刻 fail。9.json 当前的 placeholder 会在这一 push 的 CI 上被暴露 → 拿到 artifact 后单独 commit canonical 文件。

- **PR-2g.1 codex round-5 fix**（PR-2g.1 codex 五审 1 个 P3 收尾）：
  - **[r5 P3] catch Exception 不 catch Throwable**：drain engine 把 `catch (t: Throwable)` 收窄为 `catch (e: Exception)`。`Throwable` 会吞 `OutOfMemoryError` / `LinkageError` / `StackOverflowError` 等 JVM 级 fatal Error，per-row retry 没意义；改成 Exception 让 Error 上抛到 WorkManager 由它自己的 restart 语义处理。`CancellationException` 在它之前已经有专门 catch + rethrow，保护未变。

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
