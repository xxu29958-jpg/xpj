package com.ticketbox.data.repository

import android.util.Log
import com.squareup.moshi.JsonAdapter
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.ConfirmedStreamPruneScope
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.ExpenseOffsetStreamEntity
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ConfirmedExpensesApiQuery
import com.ticketbox.data.remote.ExpenseListFilterQuery
import com.ticketbox.data.remote.PageQuery
import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.domain.model.normalizedTagNames
import com.ticketbox.security.SessionCredentialProvider
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.combine
import kotlinx.coroutines.flow.distinctUntilChanged
import kotlinx.coroutines.flow.flatMapLatest
import kotlinx.coroutines.flow.first
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
) {
    val isFullLedger: Boolean get() = month == null && category == null && tag == null
}

private fun ConfirmedSyncRequest.matchesCachedOffset(
    offset: ExpenseOffsetStreamEntity,
    root: Expense?,
): Boolean {
    val cleanMonth = month?.trim().orEmpty()
    val cleanCategory = category?.trim().orEmpty()
    val cleanTag = tag?.trim().orEmpty()
    return (cleanMonth.isEmpty() || offset.streamDate.startsWith(cleanMonth)) &&
        (cleanCategory.isEmpty() || offset.category == cleanCategory) &&
        (cleanTag.isEmpty() || root?.normalizedTagNames()?.any { it.equals(cleanTag, ignoreCase = true) } == true)
}

internal class ExpenseRepositoryCore(
    val expenseDao: ExpenseDao,
    val binding: ServerSessionBinding,
    val deviceNameProvider: () -> String,
    val sessionCoordinator: LocalLedgerSessionCoordinator,
    val offlineMutations: ExpenseOfflineMutationWiring,
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
    val offsetCreateAdapter: JsonAdapter<ExpenseOffsetCreateRequestDto>?
        get() = offlineMutations.offsetCreateAdapter
    val offsetVoidAdapter: JsonAdapter<ExpenseOffsetVoidOutboxPayload>?
        get() = offlineMutations.offsetVoidAdapter

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
     * 「确认态写入本地缓存」的单点回调（轴 6 预算超支检测的触发接缝）。[cacheServerExpense]
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

    suspend fun cacheServerExpense(dto: ExpenseDto, bound: BoundLedgerRequest): ExpenseDto {
        val accepted = withActiveBindingCommit(bound) {
            val accepted = expenseDao.applyServerExpense(bound.ledgerId, dto.toEntity(bound.ledgerId))
            if (accepted && dto.status == "confirmed") notifyConfirmedExpenseWrite(bound.ledgerId, onConfirmedCommitted)
            accepted
        }
        if (accepted && dto.status != "confirmed") acknowledgeExpenseRefresh(bound, mapOf(dto.id to dto.rowVersion))
        return dto
    }

    suspend fun fetchAuthoritativeExpense(bound: BoundLedgerRequest, id: Long): ExpenseDto {
        val dto = cacheServerExpense(bound.call { it.expense(id) }, bound)
        if (dto.status == "confirmed") {
            val needsProjection = outbox?.observeActiveByTypes(EXPENSE_REFRESH_TYPES,
                includeCompleted = true)?.first()?.any {
                expenseRefreshTargetId(it.targetId, it.receiptJson) == id && it.requiresExpenseRefresh()
            } == true
            if (needsProjection) syncConfirmedFromService(bound)
        }
        return dto
    }

    /** Marker cleanup must not turn a successful mutation into an offline enqueue. */
    suspend fun acknowledgeExpenseRefresh(bound: BoundLedgerRequest, versions: Map<Long, Long>) {
        try {
            outbox?.acknowledgeExpenseRefresh(bound, versions)
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (bindingError: RepositoryException) {
            throw bindingError
        } catch (_: Exception) {
            // The durable requirement remains visible and can be acknowledged by the next read.
        }
    }

    private suspend fun confirmedStreamPruneScope(
        bound: BoundLedgerRequest,
        request: ConfirmedSyncRequest,
    ): ConfirmedStreamPruneScope {
        if (request.replaceCache) return ConfirmedStreamPruneScope(null, null)
        return withActiveBindingCommit(bound) {
            val ledgerId = bound.ledgerId
            val rootsByServerId = expenseDao.getConfirmed(ledgerId)
                .mapNotNull { root -> root.serverId?.let { it to root.toDomain() } }
                .toMap()
            ConfirmedStreamPruneScope(
                rootServerIds = if (request.isFullLedger) rootsByServerId.keys else null,
                offsetPublicIds = expenseDao.getConfirmedStreamOffsets(ledgerId)
                    .filter { offset -> request.matchesCachedOffset(offset, rootsByServerId[offset.rootServerId]) }
                    .mapTo(mutableSetOf()) { it.publicId },
            )
        }
    }

    private suspend fun fetchConfirmedStream(
        bound: BoundLedgerRequest,
        request: ConfirmedSyncRequest,
    ): List<ConfirmedExpenseStreamItemDto> {
        val collectedDtos = mutableListOf<ConfirmedExpenseStreamItemDto>()
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
        return collectedDtos
    }

    suspend fun syncConfirmedFromService(
        bound: BoundLedgerRequest,
        request: ConfirmedSyncRequest = ConfirmedSyncRequest(),
        requiredCorrection: ExpenseDto? = null,
    ): List<Expense> {
        val ledgerIdAtRequest = bound.ledgerId
        // Snapshot prune eligibility before the first page request. Rows cached
        // during pagination must survive until the next reconciliation.
        val pruneScope = confirmedStreamPruneScope(bound, request)
        val collectedDtos = fetchConfirmedStream(bound, request)

        val cacheItems = collectedDtos.map { it.toConfirmedStreamCacheItem(ledgerIdAtRequest) }
        val roots = cacheItems
            .groupBy { requireNotNull(it.root.serverId) }
            .values
            .map { candidates ->
                candidates.firstOrNull { it.root.streamDate != null }?.root ?: candidates.first().root
            }
        val offsets = cacheItems.mapNotNull { it.offset }
        if (requiredCorrection != null && roots.none {
                it.serverId == requiredCorrection.id && it.publicId == requiredCorrection.publicId &&
                    it.rowVersion >= requiredCorrection.rowVersion && it.streamDate != null
            }) throw RepositoryException("更正已送达，流水投影尚待刷新。")
        val collected = roots.map { it.toDomain() }
        val acceptedRootIds = withActiveBindingCommit(bound) {
            val accepted = expenseDao.applyConfirmedStreamSyncForLedger(
                ledgerId = ledgerIdAtRequest,
                roots = roots,
                offsets = offsets,
                replaceCache = request.replaceCache,
                pruneScope = pruneScope,
            )
            if (requiredCorrection != null && requiredCorrection.id !in accepted) {
                throw RepositoryException("更正已送达，流水投影尚待刷新。")
            }
            if (request.recordSyncTimestamp && request.isFullLedger) {
                settingsStore.saveLastConfirmedSyncAtForLedger(ledgerIdAtRequest, Instant.now().toString())
            }
            accepted
        }
        // A root month can omit an offset in another month. Only the complete projection repairs the receipt.
        if (request.isFullLedger) {
            acknowledgeExpenseRefresh(bound, roots.filter { it.streamDate != null && it.serverId in acceptedRootIds }
                .associate { requireNotNull(it.serverId) to it.rowVersion })
            // The advisor also consumes the complete set; a filtered fingerprint would flap.
            onFullConfirmedSyncSnapshot(
                "entries=${collectedDtos.size};roots=${roots.size};" +
                    "rv=${roots.maxOfOrNull { it.rowVersion } ?: 0};" +
                    "ua=${roots.maxOfOrNull { it.updatedAt.orEmpty() }.orEmpty()}",
            )
        }
        return collected
    }

    /** Fired with a cheap stable stamp after each applied FULL-ledger confirmed
     *  sync. Wired in AppContainer to the budget-advice freshness sink
     *  (var per the [onConfirmedCommitted] precedent). */
    var onFullConfirmedSyncSnapshot: (stamp: String) -> Unit = {}

    /** A ledger-scoped initial snapshot for PendingViewModel; lists, detail reads and accepted writes share Room. */
    suspend fun getCachedPending(ledgerId: String = activeLedgerIdOrLegacy()): List<Expense> =
        expenseDao.getPending(ledgerId).map { it.toDomain() }

    /** Merge the list with accepted detail/write responses that arrived while its HTTP request was in flight. */
    suspend fun syncPendingFromService(bound: BoundLedgerRequest): List<Expense> {
        val pruneVersions = withActiveBindingCommit(bound) {
            expenseDao.getPending(bound.ledgerId).mapNotNull { row -> row.serverId?.let { it to row.rowVersion } }.toMap()
        }
        val dtos = bound.call { it.pendingExpenses() }
        return withActiveBindingCommit(bound) {
            expenseDao.applyPendingSyncForLedger(bound.ledgerId, dtos.map { it.toEntity(bound.ledgerId) }, pruneVersions)
            val receivedById = dtos.associateBy { it.id }
            getCachedPending(bound.ledgerId).map { expense ->
                // Room owns the accepted fact. A live task describes only its matching response revision.
                val received = receivedById[expense.id]?.takeIf {
                    it.publicId == expense.publicId && it.rowVersion == expense.rowVersion
                }
                expense.copy(fxTask = received?.fxTask?.toDomain())
            }
        }
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
            outboxRef.withActiveBinding(bound) { block() }
        }
    }

    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    fun observeConfirmed(): Flow<List<Expense>> =
        apiProvider.observeActiveLedgerId()
            .map { it?.takeIf { id -> id.isNotBlank() } ?: LedgerRequestGuard.LEGACY_LEDGER_ID }
            .distinctUntilChanged()
            .flatMapLatest { id -> expenseDao.observeConfirmed(id).map { rows -> rows.map { it.toDomain() } } }

    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    fun observeConfirmedStream(): Flow<List<ConfirmedStreamItem>> =
        apiProvider.observeActiveLedgerId()
            .map { it?.takeIf { id -> id.isNotBlank() } ?: LedgerRequestGuard.LEGACY_LEDGER_ID }
            .distinctUntilChanged()
            .flatMapLatest { ledgerId ->
                combine(
                    expenseDao.observeConfirmed(ledgerId),
                    expenseDao.observeConfirmedStreamOffsets(ledgerId),
                ) { _, _ ->
                    // Query flows notify independently, even after one database
                    // transaction. Read the pair together instead of combining
                    // a new refund with the preceding root notification.
                    val snapshot = expenseDao.getConfirmedStreamSnapshot(ledgerId)
                    confirmedStreamFromCache(snapshot.roots, snapshot.offsets)
                }
            }

    fun activeLedgerIdOrLegacy(): String = ledgerRequestGuard.activeLedgerIdOrLegacy()

    suspend fun clearLocalCache() {
        sessionCoordinator.clearLocalCache()
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
        outbox != null && expenseStateTokenAdapter != null && expense.hasExpenseMutationBaseline()

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
        if (outboxRef == null || adapter == null || !expense.hasExpenseMutationBaseline()) {
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

    /** One bound transaction saves the original command and its optimistic negative-ID projection. */
    suspend fun enqueueLocalCreate(
        bound: BoundLedgerRequest,
        draft: ExpenseDraft,
        clientRef: String,
    ): Expense {
        val entity = draft.toLocalCreateEntity(bound.ledgerId, clientRef)
        var rowId = 0L
        offlineMutations.outbox.enqueue(
            boundRequest = bound,
            intent = PendingMutationIntent(
                type = PendingMutationType.CreateExpense,
                targetId = expenseLocalTargetId(clientRef),
                payloadJson = offlineMutations.manualCreateAdapter.toJson(draft.toManualCreateRequest(clientRef = clientRef)),
                expectedRowVersion = FIRST_WRITE_ROW_VERSION,
            ),
            afterPersisted = {
                rowId = expenseDao.insert(entity)
            },
        )
        // Notification cannot turn a committed original into an apparent save failure.
        try {
            onConfirmedCommitted(bound.ledgerId)
        } catch (cancelled: kotlinx.coroutines.CancellationException) {
            throw cancelled
        } catch (_: Exception) {
            // The Room observation and ordinary sync still expose the saved original.
        }
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
