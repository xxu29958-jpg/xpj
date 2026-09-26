package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.Moshi
import com.ticketbox.data.local.*
import com.ticketbox.data.remote.dto.*
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map
import kotlinx.coroutines.flow.first
import java.io.IOException
import java.util.UUID

@JsonClass(generateAdapter = true)
data class MonthlyArrangementDraft(val homeCurrencyCode: String, val savings: String, val buffer: String,
    val expectedRowVersion: Long?, val edited: Boolean = false) {
    fun request(): MonthlyArrangementSaveRequest {
        val currency = requireNotNull(CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode)) { "安排币种无法确认。" }
        fun amount(value: String): Long = requireNotNull(com.ticketbox.domain.model.parseExactMoneyMinor(value, currency)) {
            "请输入非负金额，并符合币种精度和金额上限。"
        }
        return MonthlyArrangementSaveRequest(homeCurrencyCode, amount(savings), amount(buffer), expectedRowVersion)
    }
}
data class MonthlyArrangementRead(val response: MonthlyArrangementResponseDto, val fromCache: Boolean = false)
data class MonthlyArrangementHistoryRead(val response: MonthlyArrangementHistoryDto, val fromCache: Boolean = false)
interface MonthlyArrangementActions {
    suspend fun arrangement(binding: LogicalSessionBinding, month: String): Result<MonthlyArrangementRead>
    suspend fun arrangementHistory(binding: LogicalSessionBinding, month: String, beforeVersion: Long? = null): Result<MonthlyArrangementHistoryRead>
    suspend fun arrangementDraft(binding: LogicalSessionBinding, month: String): MonthlyArrangementDraft?
    suspend fun storeArrangementDraft(binding: LogicalSessionBinding, month: String, draft: MonthlyArrangementDraft?)
    fun observeArrangements(binding: LogicalSessionBinding): Flow<List<PendingMonthlyArrangement>>
    fun describeArrangement(row: OutboxRow): PendingMonthlyArrangement?
    suspend fun enqueueArrangement(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest): Result<Long>
    suspend fun recoverArrangement(binding: LogicalSessionBinding, pending: PendingMonthlyArrangement, drop: Boolean): Result<Unit>
}

class MonthlyArrangementRepository(private val apiProvider: ApiServiceProvider, private val outbox: OutboxRepository,
    private val dao: MonthlyArrangementCacheDao, private val payloadAdapter: JsonAdapter<MonthlyArrangementPayload>,
    private val receiptAdapter: JsonAdapter<MonthlyArrangementDto>,
    private val onSnapshot: (String, String) -> Unit) : MonthlyArrangementActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler({ apiProvider.currentSession()?.serverUrl }, "MonthlyArrangement")
    private val moshi = Moshi.Builder().build()
    private val bindings = moshi.adapter(LogicalSessionBinding::class.java)
    private val saved = moshi.adapter(MonthlyArrangementResponseDto::class.java).serializeNulls()
    private val history = moshi.adapter(MonthlyArrangementHistoryDto::class.java)
    private val drafts = moshi.adapter(MonthlyArrangementDraft::class.java).serializeNulls()
    // Durable ownership follows the existing outbox identity; selection revisions only guard requests.
    private fun persistentBindingKey(binding: LogicalSessionBinding) = bindings.toJson(binding.copy(
        serverUrl = requireNotNull(canonicalServerOriginOrNull(binding.serverUrl)),
        ledgerId = binding.ledgerId.trim(), sessionGeneration = "", bindingRevision = ""))
    override suspend fun arrangement(binding: LogicalSessionBinding, month: String) = errors.safeCall {
        val clean = validatedBudgetMonth(month).getOrThrow()
        val bound = guard.bindExact(binding)
        val key = persistentBindingKey(binding)
        var cached = false
        val response = try { bound.call { it.monthlyArrangement(clean) } }
        catch (error: IOException) {
            bound.requireStillActive()
            cached = true
            val local = dao.read(key, clean, "saved")?.let { saved.fromJson(it.json) }
            val receipt = observeArrangements(binding).first().filter { it.isConfirmed && it.receipt?.month == clean }
                .maxByOrNull { it.receipt?.rowVersion ?: 0 }?.receipt
            if (receipt != null && receipt.rowVersion > (local?.arrangement?.rowVersion ?: 0)) {
                val projection = MonthlyArrangementResponseDto(binding.ledgerId, clean, receipt)
                dao.write(MonthlyArrangementCacheEntity(key, clean, "saved", saved.toJson(projection)))
                projection
            } else local ?: throw error
        }
        require(response.ledgerId == binding.ledgerId && response.month == clean)
        response.arrangement?.let { require(it.ledgerId == binding.ledgerId && it.month == clean && it.rowVersion > 0 &&
            CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode)?.storageKey == it.homeCurrencyCode &&
            it.savingsTargetCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX && it.reservedBufferCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX) }
        val json = saved.toJson(response)
        if (!cached) { dao.write(MonthlyArrangementCacheEntity(key, clean, "saved", json)); onSnapshot("arrangement:$key:$clean", json) }
        MonthlyArrangementRead(response, cached)
    }
    override suspend fun arrangementHistory(binding: LogicalSessionBinding, month: String, beforeVersion: Long?) = errors.safeCall {
        val clean = validatedBudgetMonth(month).getOrThrow()
        val bound = guard.bindExact(binding)
        val key = persistentBindingKey(binding)
        val kind = "history:${beforeVersion ?: 0}"
        var cached = false
        val response = try { bound.call { it.monthlyArrangementHistory(clean, beforeVersion) } }
        catch (error: IOException) {
            bound.requireStillActive()
            cached = true
            dao.read(key, clean, kind)?.let { history.fromJson(it.json) } ?: throw error
        }
        require(response.ledgerId == binding.ledgerId && response.month == clean)
        require(response.items.all { it.rowVersion > 0 && it.savingsTargetCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX && it.reservedBufferCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX &&
            CurrencyCode.fromStorageKeyOrNull(it.homeCurrencyCode)?.storageKey == it.homeCurrencyCode })
        if (!cached) dao.write(MonthlyArrangementCacheEntity(key, clean, kind, history.toJson(response)))
        MonthlyArrangementHistoryRead(response, cached)
    }
    override suspend fun arrangementDraft(binding: LogicalSessionBinding, month: String) =
        dao.read(persistentBindingKey(binding), month, "draft")?.let { drafts.fromJson(it.json) }
    override suspend fun storeArrangementDraft(binding: LogicalSessionBinding, month: String, draft: MonthlyArrangementDraft?) {
        val key = persistentBindingKey(binding)
        if (draft == null) dao.removeDraft(key, month)
        else dao.write(MonthlyArrangementCacheEntity(key, month, "draft", drafts.toJson(draft)))
    }
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
    override suspend fun enqueueArrangement(binding: LogicalSessionBinding, month: String, request: MonthlyArrangementSaveRequest) = errors.safeCall {
        check(ledgerRoleCanModify(apiProvider.currentLedgerRole())) { "当前角色为只读。" }
        val bound = guard.bindExact(binding)
        val clean = validatedBudgetMonth(month).getOrThrow()
        require(CurrencyCode.fromStorageKeyOrNull(request.homeCurrencyCode)?.storageKey == request.homeCurrencyCode &&
            request.savingsTargetCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX && request.reservedBufferCents in 0..com.ticketbox.domain.model.MONEY_MINOR_MAX && (request.expectedRowVersion == null || request.expectedRowVersion > 0))
        outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(PendingMutationType.SaveMonthlyArrangement,
            "monthly_arrangement:$clean", payloadAdapter.toJson(MonthlyArrangementPayload(1, clean, request.copy(expectedRowVersion = null))),
            request.expectedRowVersion ?: 0, UUID.randomUUID().toString()), validateTargetRows = { rows ->
            check(rows.isEmpty()) { "这月安排有待处理的保存，请先核对原提交。" }
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
