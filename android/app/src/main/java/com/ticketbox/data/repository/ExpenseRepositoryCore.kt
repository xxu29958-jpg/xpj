package com.ticketbox.data.repository

import android.util.Log
import com.squareup.moshi.JsonAdapter
import com.ticketbox.BuildConfig
import com.ticketbox.data.local.ExpenseDao
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.TicketboxSettingsStore
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.ledgerRoleCanModify
import com.ticketbox.security.SessionTokenStore
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

internal class ExpenseRepositoryCore(
    val expenseDao: ExpenseDao,
    val settingsStore: TicketboxSettingsStore,
    val tokenStore: SessionTokenStore,
    val deviceNameProvider: () -> String,
    val apiProvider: ApiServiceProvider,
    val sessionCoordinator: LocalLedgerSessionCoordinator,
    /**
     * ADR-0038 PR-2g.3: outbox surface for the call sites that
     * route through it on network failure. ``null`` keeps every
     * pre-existing test that didn't wire the outbox at the old
     * behaviour — the IOException catch in
     * [ExpensePendingRepository.updateExpense] no-ops when either
     * the outbox OR the matching payload adapter is missing.
     */
    val outbox: OutboxRepository? = null,
    val patchExpenseAdapter: JsonAdapter<ExpenseUpdateRequest>? = null,
    /**
     * ADR-0038 PR-2g.7: token-only payload adapter shared between the
     * offline-aware confirm / reject call sites
     * ([ExpensePendingRepository.confirmExpenseAllowingOffline] /
     * ``rejectExpenseAllowingOffline``) and the matching dispatchers.
     * ``null`` keeps pre-PR-2g.7 tests (no outbox wiring) on the
     * direct-only path — the IOException catch falls back to a hard
     * failure when either the outbox OR this adapter is missing.
     */
    val expenseStateTokenAdapter: JsonAdapter<ExpenseStateTokenRequest>? = null,
    /**
     * PR-D: body-carrying payload adapter shared between the offline-aware
     * items editor ([ExpenseDetailRepository.replaceExpenseItemsAllowingOffline])
     * and [ReplaceItemsDispatcher]. ``null`` keeps pre-PR-D tests (no outbox
     * wiring) on the direct-only path — the IOException catch falls back to a
     * hard failure when either the outbox OR this adapter is missing.
     */
    val replaceItemsAdapter: JsonAdapter<ExpenseItemReplaceRequestDto>? = null,
    /**
     * ADR-0042 Slice E-1: body-carrying payload adapter shared between the
     * offline-aware splits editor
     * ([ExpenseDetailRepository.replaceExpenseSplitsAllowingOffline]) and
     * [ReplaceSplitsDispatcher]. ``null`` keeps pre-Slice-E-1 tests (no outbox
     * wiring) on the direct-only path — the IOException catch falls back to a
     * hard failure when either the outbox OR this adapter is missing.
     */
    val replaceSplitsAdapter: JsonAdapter<ExpenseSplitReplaceRequestDto>? = null,
    /**
     * ADR-0042 Slice E-2: body-carrying payload adapter shared between the
     * offline-aware "粘贴文字识别"
     * ([ExpenseDetailRepository.recognizeTextAllowingOffline]) and
     * [RecognizeTextDispatcher]. ``null`` keeps pre-Slice-E-2 tests (no outbox
     * wiring) on the direct-only path — the IOException catch falls back to a
     * hard failure when either the outbox OR this adapter is missing.
     */
    val recognizeTextAdapter: JsonAdapter<ExpenseRecognizeTextRequestDto>? = null,
) {
    val errorHandler = NetworkErrorHandler(
        settingsStore = settingsStore,
        context = "Repository",
        statusMessages = mapOf(
            404 to "账单不存在。",
            413 to "上传文件超过大小限制。",
        ),
    )
    val ledgerRequestGuard = LedgerRequestGuard(settingsStore, tokenStore, apiProvider)

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

    fun currentLedgerRole(): String? = settingsStore.role()

    fun canModifyLedger(): Boolean = ledgerRoleCanModify(settingsStore.role())

    fun observeActiveLedgerId(): Flow<String?> = settingsStore.observeActiveLedgerId()

    fun currentActiveLedgerId(): String? = settingsStore.activeLedgerId()

    fun api(serverUrl: String, token: String): ApiService =
        apiProvider.temporary(serverUrl, token)

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
                Log.w(NETWORK_LOG_TAG, networkDiagnosticMessage(error, settingsStore.serverUrl()), error)
                userNetworkMessage(error, settingsStore.serverUrl())
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
        val expectedLedgerId = expectedSnapshot.activeLedgerId?.takeIf { it.isNotBlank() }
        sessionCoordinator.applyTransitionIfCurrent(
            expectedSnapshot = expectedSnapshot,
            identity = LedgerSessionIdentity(
                accountName = check.accountName,
                ledgerId = check.ledgerId,
                ledgerName = check.ledgerName,
                deviceName = check.deviceName,
                role = check.role,
                boundAt = settingsStore.boundAt() ?: Instant.now().toString(),
            ),
            cacheInvalidation = if (check.ledgerId != expectedLedgerId) {
                LedgerCacheInvalidation.TargetLedger
            } else {
                LedgerCacheInvalidation.None
            },
        )
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
            identity = LedgerSessionIdentity(
                accountName = settings.accountName,
                ledgerId = ledgerId,
                ledgerName = settings.ledgerName,
                deviceName = settings.deviceName,
                role = settings.role,
                boundAt = settingsStore.boundAt() ?: Instant.now().toString(),
            ),
        )
    }

    suspend fun cacheIfConfirmed(dto: ExpenseDto, ledgerIdAtRequest: String): ExpenseDto {
        if (dto.status == "confirmed" && activeLedgerIdOrLegacy() == ledgerIdAtRequest) {
            expenseDao.upsertByServerIdForLedger(ledgerIdAtRequest, dto.toEntity(ledgerIdAtRequest))
            onConfirmedCommitted(ledgerIdAtRequest)
        }
        return dto
    }

    suspend fun syncConfirmedFromService(
        service: ApiService,
        ledgerIdAtRequest: String = activeLedgerIdOrLegacy(),
        month: String? = null,
        category: String? = null,
        tag: String? = null,
        replaceCache: Boolean = false,
        recordSyncTimestamp: Boolean = true,
    ): List<Expense> {
        val isFullLedgerSync = month == null && category == null && tag == null
        // Prune-eligibility snapshot BEFORE the first page request: a row
        // confirmed (and cached via cacheIfConfirmed) while the paginated
        // fetch is in flight is missing from the response by timing alone —
        // it must not be pruned as "server-deleted". See
        // ExpenseDao.applyConfirmedSyncForLedger's pruneScope contract.
        val preSyncConfirmedServerIds: Set<Long> = if (!replaceCache && isFullLedgerSync) {
            expenseDao.confirmedServerIdsForLedger(ledgerIdAtRequest).toSet()
        } else {
            emptySet()
        }
        val collectedDtos = mutableListOf<ExpenseDto>()
        var page = 1
        val pageSize = 50
        var total = Int.MAX_VALUE
        do {
            if (activeLedgerIdOrLegacy() != ledgerIdAtRequest) {
                return emptyList()
            }
            val response = service.confirmedExpenses(
                page = page,
                pageSize = pageSize,
                month = month,
                category = category,
                tag = tag,
                timezone = currentTimezoneId(),
            )
            total = response.total
            collectedDtos += response.items
            if (response.items.isEmpty() && collectedDtos.size < total) {
                throw RepositoryException("账本同步分页异常，请稍后再试。")
            }
            page += 1
        } while (collectedDtos.size < total)

        val collected = collectedDtos.map { it.toDomain() }
        if (activeLedgerIdOrLegacy() != ledgerIdAtRequest) {
            return emptyList()
        }

        val entities = collectedDtos.map { it.toEntity(ledgerIdAtRequest) }
        expenseDao.applyConfirmedSyncForLedger(
            ledgerId = ledgerIdAtRequest,
            expenses = entities,
            replaceCache = replaceCache,
            pruneScope = if (!replaceCache && isFullLedgerSync) preSyncConfirmedServerIds else null,
        )
        if (recordSyncTimestamp && isFullLedgerSync) {
            settingsStore.saveLastConfirmedSyncAtForLedger(ledgerIdAtRequest, Instant.now().toString())
        }
        return collected
    }

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
        service: ApiService,
        ledgerIdAtRequest: String = activeLedgerIdOrLegacy(),
    ): List<Expense> {
        val dtos = service.pendingExpenses()
        if (activeLedgerIdOrLegacy() != ledgerIdAtRequest) {
            return emptyList()
        }
        val entities = dtos.map { it.toEntity(ledgerIdAtRequest) }
        expenseDao.applyPendingSyncForLedger(ledgerId = ledgerIdAtRequest, expenses = entities)
        return dtos.map { it.toDomain() }
    }

    @OptIn(kotlinx.coroutines.ExperimentalCoroutinesApi::class)
    fun observeConfirmed(): Flow<List<Expense>> =
        settingsStore.observeActiveLedgerId()
            .map { it?.takeIf { id -> id.isNotBlank() } ?: LedgerRequestGuard.LEGACY_LEDGER_ID }
            .distinctUntilChanged()
            .flatMapLatest { id -> expenseDao.observeConfirmed(id).map { rows -> rows.map { it.toDomain() } } }

    fun activeLedgerIdOrLegacy(): String = ledgerRequestGuard.activeLedgerIdOrLegacy()

    suspend fun clearLocalCache() {
        expenseDao.clear()
        settingsStore.clearLastConfirmedSyncAt()
    }

    suspend fun clearBinding() {
        val clearStores: suspend () -> Unit = {
            apiProvider.clear()
            expenseDao.clear()
            settingsStore.clear()
            tokenStore.clear()
        }
        if (outbox != null) {
            outbox.withBindingTransition(clearExistingRows = true) {
                clearStores()
            }
        } else {
            clearStores()
        }
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
    suspend fun hasUnresolvedQueuedMutationsFor(expenseId: Long): Boolean =
        outbox?.activeForTarget(expenseTargetId(expenseId))?.isNotEmpty() ?: false

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
        bound.requireStillActive()
        outboxRef.enqueue(
            type = type,
            targetId = expenseTargetId(expense.id),
            payloadJson = adapter.toJson(ExpenseStateTokenRequest(expectedRowVersion = 0L)),
            expectedRowVersion = expense.rowVersion,
            idempotencyKey = idempotencyKey,
        )
    }

    companion object {
        const val NETWORK_LOG_TAG = "TicketboxNetwork"
    }
}
