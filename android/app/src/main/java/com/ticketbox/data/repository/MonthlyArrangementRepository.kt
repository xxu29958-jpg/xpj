package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.local.*
import com.ticketbox.data.remote.dto.*
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.MonthlyArrangementHistory
import com.ticketbox.domain.model.MonthlyArrangementHistoryItem
import com.ticketbox.domain.model.MonthlyArrangementResponse
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.time.Instant
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import retrofit2.HttpException

@JsonClass(generateAdapter = true)
data class MonthlyArrangementDraft(val homeCurrencyCode: String, val savings: String, val buffer: String,
    val expectedRowVersion: Long?, val edited: Boolean = false) {
    fun request(): com.ticketbox.domain.model.MonthlyArrangementChange {
        val currency = requireNotNull(CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)) { "安排币种无法确认。" }
        fun amount(value: String): Long = requireNotNull(com.ticketbox.domain.model.parseExactMoneyMinor(value, currency)) {
            "请输入非负金额，并符合币种精度和金额上限。"
        }
        return com.ticketbox.domain.model.MonthlyArrangementChange(homeCurrencyCode, amount(savings), amount(buffer), expectedRowVersion)
    }
}
data class MonthlyArrangementRead(val response: com.ticketbox.domain.model.MonthlyArrangementResponse, val fromCache: Boolean = false)
data class MonthlyArrangementHistoryRead(val response: com.ticketbox.domain.model.MonthlyArrangementHistory, val fromCache: Boolean = false,
    val fetchedAt: Instant? = null, val receiptVersions: Set<Long> = emptySet())
/** Legacy raw pages remain readable; absent metadata never becomes a new read time. */
@JsonClass(generateAdapter = true)
internal data class MonthlyArrangementHistoryCache(val response: MonthlyArrangementHistory? = null,
    val fetchedAt: String? = null, val receipts: List<MonthlyArrangementHistoryItem> = emptyList())
interface MonthlyArrangementActions {
    suspend fun arrangement(binding: LogicalSessionBinding, month: String): Result<MonthlyArrangementRead>
    suspend fun arrangementHistory(binding: LogicalSessionBinding, month: String, beforeVersion: Long? = null): Result<MonthlyArrangementHistoryRead>
    suspend fun arrangementDraft(binding: LogicalSessionBinding, month: String): MonthlyArrangementDraft?
    suspend fun storeArrangementDraft(binding: LogicalSessionBinding, month: String, draft: MonthlyArrangementDraft)
    suspend fun consumeArrangementDraft(binding: LogicalSessionBinding, month: String, queuedDraft: MonthlyArrangementDraft)
    fun observeArrangements(binding: LogicalSessionBinding): Flow<List<PendingMonthlyArrangement>>
    fun describeArrangement(row: OutboxRow): PendingMonthlyArrangement?
    suspend fun enqueueArrangement(binding: LogicalSessionBinding, month: String, request: com.ticketbox.domain.model.MonthlyArrangementChange): Result<Long>
    suspend fun recoverArrangement(binding: LogicalSessionBinding, pending: PendingMonthlyArrangement, drop: Boolean): Result<Unit>
}

class MonthlyArrangementRepository internal constructor(private val apiProvider: ApiServiceProvider, private val outbox: OutboxRepository,
    private val dao: MonthlyArrangementCacheDao, adapters: BudgetMutationAdapters,
    private val onSnapshot: (String, String) -> Unit,
    private val coordinator: LocalLedgerSessionCoordinator) : MonthlyArrangementActions {
    private val payloadAdapter = adapters.arrangementSaveAdapter
    private val receiptAdapter = adapters.arrangementReceiptAdapter
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "MonthlyArrangement")
    private val moshi = Moshi.Builder().build()
    private val saved = moshi.adapter(MonthlyArrangementResponse::class.java).serializeNulls()
    private val history = moshi.adapter(MonthlyArrangementHistory::class.java)
    private val historyCache = moshi.adapter(MonthlyArrangementHistoryCache::class.java)
    private val drafts = moshi.adapter(MonthlyArrangementDraft::class.java).serializeNulls()
    override suspend fun arrangement(binding: LogicalSessionBinding, month: String) = errors.safeCall {
        val clean = validatedBudgetMonth(month).getOrThrow()
        val bound = guard.bindExact(binding)
        val key = monthlyArrangementPersistentBindingKey(binding)
        val ticket = coordinator.beginSnapshotRead()
        val response = try { bound.call { it.monthlyArrangement(clean) } }
        catch (error: HttpException) {
            val failure = errors.httpFailure(error)
            coordinator.rejectSnapshotAccess(bound, logicalBindingAdapter.toJson(binding), failure)
            throw failure
        } catch (error: Exception) {
            if (!error.isReadTransportUnavailable()) throw error
            val receipt = observeArrangements(binding).first().filter { it.isConfirmed && it.receipt?.month == clean }
                .maxByOrNull { it.receipt?.rowVersion ?: 0 }?.receipt
            return@safeCall coordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                // A receipt can update an existing query, but cannot recreate a withdrawn query.
                val local = dao.read(key, clean, "saved")?.let { saved.fromJson(it.json) } ?: throw error
                verifyArrangementResponse(local, binding, clean)
                val projection = if (receipt != null && receipt.rowVersion > (local.arrangement?.rowVersion ?: 0)) {
                    MonthlyArrangementResponse(binding.ledgerId, clean, receipt)
                } else local
                verifyArrangementResponse(projection, binding, clean)
                dao.write(MonthlyArrangementCacheEntity(key, clean, "saved", saved.toJson(projection)))
                MonthlyArrangementRead(projection, fromCache = true)
            }
        }
        verifyArrangementResponse(response, binding, clean)
        val json = saved.toJson(response)
        coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { cacheAllowed ->
            if (cacheAllowed) {
                dao.write(MonthlyArrangementCacheEntity(key, clean, "saved", json))
            }
            onSnapshot("arrangement:$key:$clean", json)
            MonthlyArrangementRead(response)
        }
    }
    private fun verifyArrangementResponse(response: MonthlyArrangementResponse, binding: LogicalSessionBinding, month: String) {
        require(response.ledgerId == binding.ledgerId && response.month == month)
        response.arrangement?.let { require(it.ledgerId == binding.ledgerId && it.month == month && it.rowVersion > 0 &&
            CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode)?.storageKey == it.homeCurrencyCode &&
            it.savingsTargetCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX && it.reservedBufferCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX) }
    }
    override suspend fun arrangementHistory(binding: LogicalSessionBinding, month: String, beforeVersion: Long?) = errors.safeCall {
        val clean = validatedBudgetMonth(month).getOrThrow()
        val bound = guard.bindExact(binding)
        val key = monthlyArrangementPersistentBindingKey(binding)
        val kind = "history:${beforeVersion ?: 0}"
        val ticket = coordinator.beginSnapshotRead()
        val response = try { bound.call { it.monthlyArrangementHistory(clean, beforeVersion) } }
        catch (error: HttpException) {
            val failure = errors.httpFailure(error)
            coordinator.rejectSnapshotAccess(bound, logicalBindingAdapter.toJson(binding), failure)
            throw failure
        } catch (error: Exception) {
            if (!error.isReadTransportUnavailable()) throw error
            val receipts = observeArrangements(binding).first().filter { it.isConfirmed && it.receipt?.month == clean }
                .mapNotNull { it.receipt }.map { MonthlyArrangementHistoryItem(it.rowVersion, it.updatedAt,
                    it.homeCurrencyCode, it.savingsTargetCents, it.reservedBufferCents) }
            return@safeCall coordinator.acceptSnapshotRead(ticket, bound, fromCache = true) {
                val json = dao.read(key, clean, kind)?.json ?: throw error
                val cache = requireNotNull(historyCache.fromJson(json))
                val local = cache.response ?: requireNotNull(history.fromJson(json))
                verifyArrangementHistory(local, binding, clean)
                val projection = local.withNewerReceipts(receipts + cache.receipts, beforeVersion)
                verifyArrangementHistory(projection, binding, clean)
                val queriedVersions = local.items.map { it.rowVersion }.toSet()
                val retainedReceipts = projection.items.filter { it.rowVersion !in queriedVersions }
                // Keep the query intact; cached receipt snapshots survive normal completed-outbox retention.
                if (retainedReceipts != cache.receipts) dao.write(MonthlyArrangementCacheEntity(key, clean, kind,
                    historyCache.toJson(cache.copy(response = local, receipts = retainedReceipts))))
                MonthlyArrangementHistoryRead(projection, fromCache = true, fetchedAt = cache.fetchedAt?.let(Instant::parse),
                    receiptVersions = retainedReceipts.map { it.rowVersion }.toSet())
            }
        }
        verifyArrangementHistory(response, binding, clean)
        val fetchedAt = Instant.now()
        coordinator.acceptSnapshotRead(ticket, bound, fromCache = false) { cacheAllowed ->
            if (cacheAllowed) dao.write(MonthlyArrangementCacheEntity(key, clean, kind,
                historyCache.toJson(MonthlyArrangementHistoryCache(response, fetchedAt.toString()))))
            MonthlyArrangementHistoryRead(response, fetchedAt = fetchedAt)
        }
    }
    private fun verifyArrangementHistory(response: MonthlyArrangementHistory, binding: LogicalSessionBinding, clean: String) {
        require(response.ledgerId == binding.ledgerId && response.month == clean)
        require(response.items.all { it.rowVersion > 0 && it.savingsTargetCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX && it.reservedBufferCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX &&
            CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode)?.storageKey == it.homeCurrencyCode })
    }
    override suspend fun arrangementDraft(binding: LogicalSessionBinding, month: String) =
        dao.read(monthlyArrangementPersistentBindingKey(binding), month, "draft")?.let { drafts.fromJson(it.json) }
    override suspend fun storeArrangementDraft(binding: LogicalSessionBinding, month: String, draft: MonthlyArrangementDraft) {
        val key = monthlyArrangementPersistentBindingKey(binding)
        dao.write(MonthlyArrangementCacheEntity(key, month, "draft", drafts.toJson(draft)))
    }
    override suspend fun consumeArrangementDraft(binding: LogicalSessionBinding, month: String, queuedDraft: MonthlyArrangementDraft) =
        dao.consumeDraft(monthlyArrangementPersistentBindingKey(binding), month, drafts.toJson(queuedDraft))
    override fun observeArrangements(binding: LogicalSessionBinding): Flow<List<PendingMonthlyArrangement>> =
        outbox.observeActiveByTypes(setOf(PendingMutationType.SaveMonthlyArrangement), includeCompleted = true).map { rows ->
            if (guard.captureLogicalBinding() != binding) emptyList() else rows.mapNotNull(::describeArrangement)
        }
    override fun describeArrangement(row: OutboxRow): PendingMonthlyArrangement? {
        val binding = guard.captureLogicalBinding() ?: return null
        if (row.type != PendingMutationType.SaveMonthlyArrangement || row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId ||
            canonicalServerOriginOrNull(row.serverUrl) != canonicalServerOriginOrNull(binding.serverUrl)) return null
        val intent = payloadAdapter.readArrangement(row.payloadJson)?.takeIf { it.supports(row) }
        val receipt = row.receiptJson?.let { runCatching { receiptAdapter.fromJson(it) }.getOrNull() }?.takeIf {
            intent != null && it.ledgerId == row.ledgerId && it.month == intent.month && it.rowVersion == row.expectedRowVersion + 1 &&
                it.homeCurrencyCode == intent.request.homeCurrencyCode && it.savingsTargetCents == intent.request.savingsTargetCents &&
                it.reservedBufferCents == intent.request.reservedBufferCents
        }
        return PendingMonthlyArrangement(row, intent, receipt)
    }
    override suspend fun enqueueArrangement(binding: LogicalSessionBinding, month: String, request: com.ticketbox.domain.model.MonthlyArrangementChange) = errors.safeCall {
        check(ledgerRoleCanModify(apiProvider.currentLedgerRole())) { "当前角色为只读。" }
        val bound = guard.bindExact(binding)
        val clean = validatedBudgetMonth(month).getOrThrow()
        require(CurrencyCode.fromStorageKeyOrNull(request.homeCurrencyCode)?.storageKey == request.homeCurrencyCode &&
            request.savingsTargetCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX && request.reservedBufferCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX && (request.expectedRowVersion == null || request.expectedRowVersion > 0))
        outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(PendingMutationType.SaveMonthlyArrangement,
            "monthly_arrangement:$clean", payloadAdapter.toJson(MonthlyArrangementSubmission(1, clean, request.copy(expectedRowVersion = null))),
            request.expectedRowVersion ?: 0, UUID.randomUUID().toString()), validateTargetRows = { rows ->
            check(rows.all { it.status == PendingMutationStatus.Done }) { "这月安排有待处理的保存，请先核对原提交。" }
        })
    }
    override suspend fun recoverArrangement(binding: LogicalSessionBinding, pending: PendingMonthlyArrangement, drop: Boolean) = errors.safeCall {
        val bound = guard.bindExact(binding)
        val original = checkNotNull(describeArrangement(pending.row))
        check(drop || ledgerRoleCanModify(apiProvider.currentLedgerRole())) { "当前角色为只读。" }
        check(drop || original.canRetry) { "请先核对当前安排；冲突不能直接覆盖。" }
        when (original.row.status) {
            PendingMutationStatus.Conflict -> if (drop) outbox.resolveConflict(original.row.id, ConflictResolution.DropMine, bound)
            PendingMutationStatus.Failed -> outbox.resolveFailed(original.row.id, if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound)
            else -> Unit
        }
        Unit
    }
}

internal val logicalBindingAdapter = Moshi.Builder().build().adapter(LogicalSessionBinding::class.java)

private fun MonthlyArrangementHistory.withNewerReceipts(receipts: List<MonthlyArrangementHistoryItem>, beforeVersion: Long?): MonthlyArrangementHistory {
    val latest = items.maxOfOrNull { it.rowVersion } ?: 0
    val newer = receipts.filter { it.rowVersion > latest && (beforeVersion == null || it.rowVersion < beforeVersion) }
    if (newer.isEmpty()) return this
    val known = (newer + items).distinctBy { it.rowVersion }.sortedByDescending { it.rowVersion }
    // Preserve known revisions; a receipt does not prove intervening changes from another device.
    val gap = known.zipWithNext().firstOrNull { (new, old) -> new.rowVersion - old.rowVersion > 1 }?.first?.rowVersion
    val missingTail = if (items.isEmpty()) known.last().rowVersion.takeIf { it > 1 } else null
    return copy(items = known, nextBeforeVersion = gap ?: nextBeforeVersion ?: missingTail)
}

// Durable ownership follows the existing outbox identity; selection revisions only guard requests.
internal fun monthlyArrangementPersistentBindingKey(binding: LogicalSessionBinding): String =
    logicalBindingAdapter.toJson(binding.copy(
        serverUrl = requireNotNull(canonicalServerOriginOrNull(binding.serverUrl)),
        ledgerId = binding.ledgerId.trim(), sessionGeneration = "", bindingRevision = ""))
