package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import com.ticketbox.domain.model.ledgerRoleCanModify
import java.util.UUID
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.map

data class OccurrencePaymentDraft(
    val occurrence: RecurringOccurrenceDto,
    val seriesLabel: String,
    val request: RecurringOccurrencePaymentRequestDto,
    val paymentLabel: String?,
    val paymentAmountCents: Long?,
    val paymentCurrencyCode: String?,
)

data class PendingOccurrencePayment(val row: OutboxRow, val intent: RecurringOccurrencePayload?) {
    val canRetry: Boolean get() = intent?.matchesOriginal(row) == true && row.status == PendingMutationStatus.Failed &&
        (row.lastError?.startsWith("max_attempts_exceeded(") == true ||
            row.lastError in setOf("client_upgrade_required", "runtime_version_mismatch"))
}

interface RecurringOccurrenceActions {
    fun currentAccess(): LedgerAccessContext?
    fun observeAccess(): Flow<LedgerAccessContext?>
    fun describe(row: OutboxRow): PendingOccurrencePayment?
    fun observeQueue(binding: LogicalSessionBinding): Flow<List<PendingOccurrencePayment>>
    suspend fun fetch(binding: LogicalSessionBinding, seriesId: String, period: String): Result<RecurringOccurrenceDto>
    suspend fun enqueue(binding: LogicalSessionBinding, draft: OccurrencePaymentDraft): Result<Long>
    suspend fun recover(binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean): Result<Unit>
}

/** The outbox dispatcher is the sole network writer. This owner publishes original user intent first. */
class RecurringOccurrenceRepository(
    private val apiProvider: ApiServiceProvider,
    private val outbox: OutboxRepository,
    private val adapter: JsonAdapter<RecurringOccurrencePayload>,
) : RecurringOccurrenceActions {
    private val guard = LedgerRequestGuard(apiProvider)
    private val errors = NetworkErrorHandler(serverUrlProvider = { null }, context = "Recurring occurrence")

    override fun currentAccess(): LedgerAccessContext? = guard.captureLogicalBinding()?.let {
        LedgerAccessContext(it, ledgerRoleCanModify(apiProvider.currentLedgerRole()))
    }

    override fun observeAccess(): Flow<LedgerAccessContext?> = apiProvider.observeActiveLedgerAccess()

    override fun describe(row: OutboxRow): PendingOccurrencePayment? {
        val binding = currentAccess()?.binding ?: return null
        val origin = canonicalServerOriginOrNull(binding.serverUrl) ?: return null
        if (row.type != PendingMutationType.SetRecurringOccurrencePayment ||
            row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId ||
            canonicalServerOriginOrNull(row.serverUrl) != origin
        ) return null
        return PendingOccurrencePayment(row, adapter.readSupportedOccurrence(row.payloadJson))
    }

    override fun observeQueue(binding: LogicalSessionBinding): Flow<List<PendingOccurrencePayment>> =
        outbox.observeActiveByTypes(setOf(PendingMutationType.SetRecurringOccurrencePayment), includeCompleted = true)
            .map { rows ->
                if (currentAccess()?.binding != binding) emptyList() else rows.mapNotNull(::describe)
            }

    override suspend fun recover(binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean): Result<Unit> = errors.safeCall {
        val bound = guard.bindExact(binding)
        val original = checkNotNull(describe(row)) { "原提交不属于当前连接，请重新核对。" }
        check(drop || currentAccess()?.canModify == true) { "当前角色为只读，无法修改账本。" }
        check(drop || original.canRetry) { "请先核对期次与付款，原提交已保留。" }
        when (row.status) {
            PendingMutationStatus.Conflict -> if (drop) outbox.resolveConflict(row.id, ConflictResolution.DropMine, bound)
            PendingMutationStatus.Failed -> outbox.resolveFailed(row.id,
                if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound)
            else -> Unit
        }
        Unit
    }

    override suspend fun fetch(
        binding: LogicalSessionBinding,
        seriesId: String,
        period: String,
    ): Result<RecurringOccurrenceDto> = errors.safeCall {
        guard.bindExact(binding).call { it.recurringOccurrence(seriesId, period) }
    }

    override suspend fun enqueue(binding: LogicalSessionBinding, draft: OccurrencePaymentDraft): Result<Long> = try {
        val bound = guard.bindExact(binding)
        if (currentAccess()?.canModify != true) throw RepositoryException("当前角色为只读，无法修改账本。")
        val payload = draft.toPayload(binding)
        val encoded = adapter.toJson(payload)
        if (adapter.readSupportedOccurrence(encoded) == null) throw RepositoryException("请刷新本期期次后重新选择付款。")
        val id = outbox.enqueue(
            boundRequest = bound,
            intent = PendingMutationIntent(
                type = PendingMutationType.SetRecurringOccurrencePayment,
                targetId = occurrenceTarget(payload.seriesPublicId, payload.period),
                payloadJson = encoded,
                expectedRowVersion = payload.request.expectedRowVersion,
                idempotencyKey = UUID.randomUUID().toString(),
            ),
        )
        Result.success(id)
    } catch (error: CancellationException) {
        throw error
    } catch (error: RepositoryException) {
        Result.failure(error)
    } catch (_: Exception) {
        Result.failure(RepositoryException("未能确认本机保存，请保留选择并检查待同步记录。"))
    }
}

private fun OccurrencePaymentDraft.toPayload(binding: LogicalSessionBinding) = RecurringOccurrencePayload(
    revision = RECURRING_OCCURRENCE_PAYLOAD_REVISION,
    seriesPublicId = occurrence.seriesPublicId,
    seriesLabel = seriesLabel,
    period = occurrence.period,
    paymentCurrencyCode = paymentCurrencyCode,
    originSessionGeneration = binding.sessionGeneration,
    originBindingRevision = binding.bindingRevision,
    paymentLabel = paymentLabel,
    paymentAmountCents = paymentAmountCents,
    request = request,
)
