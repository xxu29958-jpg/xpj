package com.ticketbox.data.repository

import android.util.Log
import com.squareup.moshi.JsonAdapter
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ConfirmedExpensesApiQuery
import com.ticketbox.data.remote.ExpenseListFilterQuery
import com.ticketbox.data.remote.PageQuery
import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionCredentialProvider
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.map
import okhttp3.ResponseBody
import retrofit2.HttpException
import retrofit2.Response
import java.io.IOException
import java.time.Instant
import java.util.TimeZone

private const val CONFIRMED_SYNC_PAGE_SIZE = 200

internal data class ConfirmedSyncRequest(
    val month: String? = null,
    val category: String? = null,
    val tag: String? = null,
    val replaceCache: Boolean = false,
    val recordSyncTimestamp: Boolean = true,
)

internal class ExpenseRepositoryCore(
    val expenseDao: ExpenseDao,
    val binding: ServerSessionBinding,
    val deviceNameProvider: () -> String,
    val sessionCoordinator: LocalLedgerSessionCoordinator,
    val offlineMutations: ExpenseOfflineMutationWiring = ExpenseOfflineMutationWiring(),
) {
    val settingsStore: TicketboxSettingsStore
        get() = binding.settingsStore
    val tokenStore: SessionCredentialProvider
        get() = binding.credentials
    val apiProvider: ApiServiceProvider
        get() = binding.apiProvider
    val outbox: OutboxRepository?
        get() = offlineMutations.outbox
    val patchExpenseAdapter: JsonAdapter<ExpenseUpdateRequest>?
        get() = offlineMutations.patchExpenseAdapter
    val expenseStateTokenAdapter: JsonAdapter<ExpenseStateTokenRequest>?
        get() = offlineMutations.expenseStateTokenAdapter
    val replaceItemsAdapter: JsonAdapter<ExpenseItemReplaceRequestDto>?
        get() = offlineMutations.replaceItemsAdapter
    val replaceSplitsAdapter: JsonAdapter<ExpenseSplitReplaceRequestDto>?
        get() = offlineMutations.replaceSplitsAdapter
    val recognizeTextAdapter: JsonAdapter<ExpenseRecognizeTextRequestDto>?
        get() = offlineMutations.recognizeTextAdapter
    val manualCreateAdapter: JsonAdapter<ExpenseManualCreateRequestDto>?
        get() = offlineMutations.manualCreateAdapter

    val errorHandler = NetworkErrorHandler(
        serverUrlProvider = { apiProvider.currentSession()?.serverUrl },
        context = "Repository",
        statusMessages = mapOf(
            404 to "账单不存在。",
            413 to "上传文件超过大小限制。",
        ),
    )
    val ledgerRequestGuard = LedgerRequestGuard(apiProvider)

    /**
     * 「确认态写入本地缓存」的单点回调（轴 6 预算超支检测的触发接缝）。[cacheIfConfirmed]
     * 真正 upsert 后同步调用；实现必须 fire-and-forget（立即返回、内部自行 launch），
     * 不得阻塞确认链路。var 而非构造参数：facade 构造已 12 参，加参会让 detekt
     * LongParameterList baseline 按签名失配（RuleRepository 的 onConfirmedChanged 是构造注入
     * 先例，本处选 var 纯为 baseline 零搅动）。AppContainer 经
     * [ExpenseRepository.onConfirmedCommitted] 注入；默认 no-op 保持既有测试行为。
     */
    var onConfirmedCommitted: (ledgerId: String) -> Unit = {}

    fun currentTimezoneId(): String = TimeZone.getDefault().id

    fun localBinding(): LocalBindingInfo? {
        val session = apiProvider.currentSession() ?: return null
        return LocalBindingInfo(
            serverUrl = session.serverUrl,
            accountName = session.identity.accountName,
            ledgerId = session.identity.ledgerId,
            ledgerName = session.identity.ledgerName,
            deviceName = session.identity.deviceName,
            role = session.identity.role,
            boundAt = session.identity.boundAt,
        )
    }

    fun currentLedgerRole(): String? = apiProvider.currentLedgerRole()

    fun canModifyLedger(): Boolean = ledgerRoleCanModify(apiProvider.currentLedgerRole())

    fun observeActiveLedgerId(): Flow<String?> = apiProvider.observeActiveLedgerId()

    fun currentActiveLedgerId(): String? = apiProvider.currentLedgerId()

    fun readProtectedImage(response: Response<ResponseBody>): ProtectedImage {
        if (!response.isSuccessful) {
            val errorBody = response.errorBody()?.string()
            if (BuildConfig.DEBUG) {
                Log.w(NETWORK_LOG_TAG, "Protected image request failed: code=${response.code()} body=${errorBody?.take(160)}")
            }
            val parsed = errorHandler.parseErrorMessage(response.code(), errorBody)
            throw RepositoryException(parsed.message, parsed.errorCode)
        }
        val body = response.body() ?: throw RepositoryException("图片为空。")
        val contentType = body.contentType()?.toString()
        val bytes = body.use { it.bytes() }
        if (bytes.isEmpty()) {
            throw RepositoryException("图片为空。")
        }
        if (BuildConfig.DEBUG) {
            Log.d(NETWORK_LOG_TAG, "Protected image loaded: contentType=$contentType bytes=${bytes.size}")
        }
        return ProtectedImage(bytes = bytes, contentType = contentType)
    }

    fun diagnosticErrorMessage(error: Throwable): String {
        return when (error) {
            is HttpException -> errorHandler.parseHttpError(error).message
            is IOException -> {
                val serverUrl = apiProvider.currentSession()?.serverUrl
                Log.w(NETWORK_LOG_TAG, networkDiagnosticMessage(error, serverUrl), error)
                userNetworkMessage(error, serverUrl)
            }
            is RepositoryException -> error.message ?: "操作失败。"
            is IllegalArgumentException -> error.message ?: "请求参数不正确。"
            else -> error.message ?: "操作失败。"
        }
    }

    suspend fun persistAuthCheck(
        check: AuthCheckDto,
        expectedSnapshot: LedgerSessionSnapshot,
    ) {
        val expectedLedgerId = requireNotNull(
            expectedSnapshot.activeLedgerId?.takeIf { it.isNotBlank() },
        ) { "Authenticated requests require a selected ledger." }
        if (check.ledgerId != expectedLedgerId) {
            throw RepositoryException(LedgerRequestGuard.LEDGER_CHANGED_MESSAGE)
        }
        val serverId = check.serverId.requireSessionProtocolId("服务器身份")
        val dataGeneration = check.dataGeneration.requireSessionProtocolId("数据代际")
        val accountPublicId = check.accountPublicId.requireSessionProtocolId("成员身份")
        val devicePublicId = check.devicePublicId.requireSessionProtocolId("设备身份")
        val applied = sessionCoordinator.applyTransitionIfCurrent(
            expectedSnapshot = expectedSnapshot,
            transition = LedgerSessionTransition(
                change = LocalSessionChange.RefreshProjection,
                serverId = serverId,
                dataGeneration = dataGeneration,
                identity = LedgerSessionIdentity(
                    accountPublicId = accountPublicId,
                    devicePublicId = devicePublicId,
                    accountName = check.accountName,
                    ledgerId = check.ledgerId,
                    ledgerName = check.ledgerName,
                    deviceName = check.deviceName,
                    role = check.role,
                    boundAt = apiProvider.currentSession()?.identity?.boundAt ?: Instant.now().toString(),
                ),
            ),
        )
        if (!applied) throw RepositoryException(LedgerRequestGuard.LEDGER_CHANGED_MESSAGE)
    }

    suspend fun persistServerSettings(
        settings: ServerSettingsDto,
        expectedSnapshot: LedgerSessionSnapshot,
        expectedLedgerId: String?,
    ) {
        val expected = expectedLedgerId ?: return
        val ledgerId = expectedSnapshot.activeLedgerId?.takeIf { it.isNotBlank() } ?: return
        if (ledgerId != expected) return
        if (settings.ledgerId != null && settings.ledgerId != expected) return
        sessionCoordinator.applyTransitionIfCurrent(
            expectedSnapshot = expectedSnapshot,
            transition = LedgerSessionTransition(
                change = LocalSessionChange.RefreshProjection,
                identity = LedgerSessionIdentity(
                    accountPublicId = apiProvider.currentSession()?.identity?.accountPublicId,
                    devicePublicId = apiProvider.currentSession()?.identity?.devicePublicId,
                    accountName = settings.accountName,
                    ledgerId = ledgerId,
                    ledgerName = settings.ledgerName,
                    deviceName = settings.deviceName,
                    role = settings.role,
                    boundAt = apiProvider.currentSession()?.identity?.boundAt ?: Instant.now().toString(),
                ),
            ),
        )
    }

    suspend fun cacheIfConfirmed(dto: ExpenseDto, bound: BoundLedgerRequest): ExpenseDto {
        if (dto.status == "confirmed") {
            withActiveBindingCommit(bound) {
                expenseDao.upsertByServerIdForLedger(bound.ledgerId, dto.toEntity(bound.ledgerId))
                onConfirmedCommitted(bound.ledgerId)
            }
        }
        return dto
    }

    suspend fun syncConfirmedFromService(
        bound: BoundLedgerRequest,
        request: ConfirmedSyncRequest = ConfirmedSyncRequest(),
    ): List<Expense> {
        val ledgerIdAtRequest = bound.ledgerId
        val isFullLedgerSync = request.month == null && request.category == null && request.tag == null
        // Prune-eligibility snapshot BEFORE the first page request: a row
        // confirmed (and cached via cacheIfConfirmed) while the paginated
        // fetch is in flight is missing from the response by timing alone —
        // it must not be pruned as "server-deleted". See
        // ExpenseDao.applyConfirmedSyncForLedger's pruneScope contract.
        val preSyncConfirmedServerIds: Set<Long> = if (!request.replaceCache && isFullLedgerSync) {
            withActiveBindingCommit(bound) {
                expenseDao.confirmedServerIdsForLedger(ledgerIdAtRequest).toSet()
            }
        } else {
            emptySet()
        }
        val collectedDtos = mutableListOf<ExpenseDto>()
        var page = 1
        val pageSize = CONFIRMED_SYNC_PAGE_SIZE
        var total = Int.MAX_VALUE
        do {
            val response = bound.call { service ->
                service.confirmedExpenses(
                    query = ConfirmedExpensesApiQuery(
                        page = PageQuery(page = page, pageSize = pageSize),
                        filters = ExpenseListFilterQuery(
                            month = request.month,
                            category = request.category,
                            tag = request.tag,
                        ),
                        timezone = currentTimezoneId(),
                    ).toQueryMap(),
                )
            }
            total = response.total
            collectedDtos += response.items
            if (response.items.isEmpty() && collectedDtos.size < total) {
                throw RepositoryException("账本同步分页异常，请稍后再试。")
            }
            page += 1
        } while (collectedDtos.size < total)

        val collected = collectedDtos.map { it.toDomain() }
        withActiveBindingCommit(bound) {
            val entities = collectedDtos.map { it.toEntity(ledgerIdAtRequest) }
            expenseDao.applyConfirmedSyncForLedger(
                ledgerId = ledgerIdAtRequest,
                expenses = entities,
                replaceCache = request.replaceCache,
                pruneScope = if (!request.replaceCache && isFullLedgerSync) preSyncConfirmedServerIds else null,
            )
            if (request.recordSyncTimestamp && isFullLedgerSync) {
                settingsStore.saveLastConfirmedSyncAtForLedger(ledgerIdAtRequest, Instant.now().toString())
            }
        }
        // Only a full-ledger sync delivers the confirmed set the budget
        // advisor consumes; filtered syncs fingerprint a subset and would flap.
        if (isFullLedgerSync) {
            onFullConfirmedSyncSnapshot(
                "n=${collectedDtos.size};" +
                    "rv=${collectedDtos.maxOfOrNull(ExpenseDto::rowVersion) ?: 0};" +
                    "ua=${collectedDtos.maxOfOrNull(ExpenseDto::updatedAt).orEmpty()}",
            )
        }
        return collected
    }

    /** Fired with a cheap stable stamp after each applied FULL-ledger confirmed
     *  sync. Wired in AppContainer to the budget-advice freshness sink
     *  (var per the [onConfirmedCommitted] precedent). */
    var onFullConfirmedSyncSnapshot: (stamp: String) -> Unit = {}

    /**
     * issue #64 A3：pending 列表本地优先读的「读缓存」入口。从 Room 取本账本已缓存
     * 的 pending 行（[syncPendingFromService] 写回的），供 PendingViewModel 在
     * init / 换账本时立即填充列表、消掉「空白 → 骨架屏 → 网络回来」的间隙。
     * 一次性快照读，不是持续 Flow——持续 Flow 会复活 VM 已乐观移除的行
     * （confirm/reject 只改内存不写 Room），撞 review action 执行器「行为不变」红线。
     */
    suspend fun getCachedPending(ledgerId: String = activeLedgerIdOrLegacy()): List<Expense> =
        expenseDao.getPending(ledgerId).map { it.toDomain() }

    /**
     * issue #64 A3：pending 列表本地优先读的「拉远端 + 写回缓存」入口。镜像
     * [syncConfirmedFromService] 但 pending 走非分页单次 `pendingExpenses()`，整张
     * 列表原子到达，故写回用 wholesale-replace（[ExpenseDao.applyPendingSyncForLedger]，
     * 只清 pending 不动 confirmed 缓存），无需 prune。换账本守卫与 confirmed 同：
     * 拿到响应后若 active ledger 已变即丢弃，绝不把旧账本数据写进新账本缓存。
     */
    suspend fun syncPendingFromService(
        bound: BoundLedgerRequest,
    ): List<Expense> {
        val dtos = bound.call { it.pendingExpenses() }
        withActiveBindingCommit(bound) {
            val entities = dtos.map { it.toEntity(bound.ledgerId) }
            expenseDao.applyPendingSyncForLedger(ledgerId = bound.ledgerId, expenses = entities)
        }
        return dtos.map { it.toDomain() }
    }

    suspend fun <T> withActiveBindingCommit(
        bound: BoundLedgerRequest,
        block: suspend () -> T,
    ): T {
        val outboxRef = outbox
        return if (outboxRef == null) {
            bound.requireStillActive()
            block()
        } else {
            outboxRef.withActiveBinding(bound, block)
        }
    }

    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    fun observeConfirmed(): Flow<List<Expense>> =
        apiProvider.observeActiveLedgerId()
            .map { it?.takeIf { id -> id.isNotBlank() } ?: LedgerRequestGuard.LEGACY_LEDGER_ID }
            .distinctUntilChanged()
            .flatMapLatest { id -> expenseDao.observeConfirmed(id).map { rows -> rows.map { it.toDomain() } } }

    fun activeLedgerIdOrLegacy(): String = ledgerRequestGuard.activeLedgerIdOrLegacy()

    suspend fun clearLocalCache() {
        expenseDao.clear()
        apiProvider.currentLedgerId()?.let(settingsStore::clearLastConfirmedSyncAtForLedger)
    }

    suspend fun clearBinding() {
        sessionCoordinator.clearSession()
    }

    /**
     * Per-target FIFO guard for the direct-first ``*AllowingOffline``
     * mutations. ``true`` when the outbox already holds an unresolved row
     * (PENDING / IN_FLIGHT / CONFLICT / FAILED) for this expense — a direct
     * call now would jump the queue: e.g. a save that just QUEUED its PATCH
     * chains into an online confirm, the confirm lands server-side with the
     * pre-edit token (which still matches, because the PATCH never ran),
     * the row is confirmed WITHOUT the user's edit, and the queued PATCH
     * 409s on replay. Callers that CAN enqueue must divert to their enqueue
     * branch instead; callers without outbox wiring keep the direct path
     * (there is no queue to respect).
     */
    suspend fun hasUnresolvedQueuedMutationsFor(
        boundRequest: BoundLedgerRequest,
        targetId: String,
    ): Boolean = outbox?.activeForTarget(boundRequest, targetId)?.isNotEmpty() ?: false

    /**
     * Whether [enqueueStateTransition] CAN enqueue for this expense —
     * outbox + token adapter wired and the baseline carries a usable
     * token. Pre-checked by the queue-jump guard branch so its
     * ``networkError = null`` call never hits the rethrow path.
     */
    fun canEnqueueStateTransition(expense: Expense): Boolean =
        outbox != null && expenseStateTokenAdapter != null && expense.rowVersion != 0L

    /**
     * ADR-0038 PR-2g.7/8: shared IOException → outbox fallback for the
     * offline-aware token-only state-machine POSTs (confirm / reject /
     * mark-not-duplicate in [ExpensePendingRepository]; retry-OCR /
     * acknowledge-items-mismatch in [ExpenseDetailRepository]). Enqueues a
     * token-only row — the payload carries a ``0L`` placeholder and
     * ``row.expectedRowVersion`` is the single source of truth (the
     * dispatcher overwrites the request token from the row on replay —
     * round-8 P3#5). Re-checks session activity BEFORE enqueue so a
     * mid-flight ledger switch can't slip an old-session row into the
     * now-current ledger's queue (round-13 P1). Rethrows [networkError]
     * when the outbox / adapter isn't wired or the baseline lacks a token
     * (``rowVersion == 0L``), so the caller surfaces a hard failure instead
     * of pretending to have queued. [networkError] is null only on the
     * queue-jump guard path ([hasUnresolvedQueuedMutationsFor]), whose
     * caller pre-checks [canEnqueueStateTransition] — the rethrow branch is
     * unreachable there by contract.
     *
     * Lives on the core (not a single Repository) because both the
     * pending repo and the detail repo route their token-only POSTs
     * through it. The ``type = PendingMutationType.X`` literal stays at
     * each call site so the outbox-coverage audit still sees the
     * enqueue.
     */
    suspend fun enqueueStateTransition(
        bound: BoundLedgerRequest,
        type: PendingMutationType,
        expense: Expense,
        networkError: IOException?,
        // ADR-0042 Slice D-1: the intent-time idempotency key the offline-aware
        // caller already used for its direct attempt. The enqueued row carries
        // the SAME key so a committed-but-unseen first attempt (the POST
        // committed server-side but the response was lost) replays with it — the
        // server HITs the recorded success instead of false-409ing on the now-
        // stale token. The dispatcher replays it from ``row.idempotencyKey``.
        idempotencyKey: String,
    ) {
        val outboxRef = outbox
        val adapter = expenseStateTokenAdapter
        if (outboxRef == null || adapter == null || expense.rowVersion == 0L) {
            throw networkError ?: IllegalStateException(
                "enqueueStateTransition without outbox wiring — guard callers must pre-check canEnqueueStateTransition",
            )
        }
        outboxRef.enqueue(
            boundRequest = bound,
            intent = PendingMutationIntent(
                type = type,
                // A pending create is addressed by its device-local ref; a synced
                // expense keeps the server id.
                targetId = expenseOutboxTargetId(expense),
                payloadJson = adapter.toJson(ExpenseStateTokenRequest(expectedRowVersion = 0L)),
                expectedRowVersion = expense.rowVersion,
                idempotencyKey = idempotencyKey,
            ),
            afterPersisted = {
                if (type == PendingMutationType.RejectExpense && expense.status == "confirmed") {
                    expenseDao.deleteConfirmedByServerIds(bound.ledgerId, listOf(expense.id))
                }
            },
        )
    }

    /**
     * issue #65 slice 4: offline-aware manual create. The caller (online attempt
     * failed with [java.io.IOException], or there's a queued sibling) writes the
     * optimistic local row to Room and queues a [PendingMutationType.CreateExpense]
     * row keyed by ``expense:local:{clientRef}``; the returned [Expense] is the
     * optimistic projection surfaced to the UI immediately (negative local id,
     * ``pendingSync = true``).
     *
     * Mirrors [enqueueStateTransition]'s session-race guard: re-checks the bound
     * ledger is still active BEFORE writing so a mid-flight ledger switch can't
     * land a stale-session create in the now-current ledger. ``onConfirmedCommitted``
     * fires for the new confirmed row (轴 6 budget detection). The CreateExpense
     * row carries ``expectedRowVersion = 0`` (no prior version) and no
     * ``Idempotency-Key`` header — idempotency is the body ``client_ref``.
     */
    suspend fun enqueueLocalCreate(
        bound: BoundLedgerRequest,
        outbox: OutboxRepository,
        adapter: JsonAdapter<ExpenseManualCreateRequestDto>,
        draft: ExpenseDraft,
        clientRef: String,
    ): Expense {
        val entity = draft.toLocalCreateEntity(bound.ledgerId, clientRef)
        var rowId = 0L
        outbox.enqueue(
            boundRequest = bound,
            intent = PendingMutationIntent(
                type = PendingMutationType.CreateExpense,
                targetId = expenseLocalTargetId(clientRef),
                payloadJson = adapter.toJson(draft.toManualCreateRequest(clientRef = clientRef)),
                expectedRowVersion = FIRST_WRITE_ROW_VERSION,
            ),
            afterPersisted = {
                rowId = expenseDao.insert(entity)
            },
        )
        // The durable intent is committed before its optimistic projection in
        // one binding lease. Process death can lose UI sugar, never the intent.
        onConfirmedCommitted(bound.ledgerId)
        return entity.copy(id = rowId).toDomain()
    }

    companion object {
        const val NETWORK_LOG_TAG = "TicketboxNetwork"

        /**
         * issue #65 slice 4: the create has no prior server row version — mirrors
         * the backend ``expense_query.FIRST_WRITE_ROW_VERSION`` sentinel (0). The
         * server's create default ``row_version`` is 1, written back on sync.
         */
        const val FIRST_WRITE_ROW_VERSION: Long = 0L
    }
}
