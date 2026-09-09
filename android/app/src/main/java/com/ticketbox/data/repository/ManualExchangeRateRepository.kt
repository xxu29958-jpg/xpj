package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.data.remote.dto.ExchangeRateRequestDto
import com.ticketbox.domain.model.ledgerRoleCanModify
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.flow.map
import java.util.UUID

interface ManualRateActions {
    fun describeRate(row: OutboxRow): PendingManualRateSubmission?
    fun observeRates(expectedBinding: LogicalSessionBinding): Flow<List<PendingManualRateSubmission>>
    suspend fun recoverRate(expectedBinding: LogicalSessionBinding, pending: PendingManualRateSubmission, drop: Boolean): Result<Unit>
    suspend fun enqueueRate(expectedBinding: LogicalSessionBinding, month: String,
        request: ExchangeRateRequestDto, originalPublicId: String?): Result<Long>
    suspend fun exchangeRates(expectedBinding: LogicalSessionBinding, currencyCode: String? = null,
        homeCurrencyCode: String? = null, rateDate: String? = null): Result<List<ExchangeRateDto>>
}

/** The existing server FX owner accepts one captured pair/date command from the shared queue. */
class ManualExchangeRateRepository(private val provider: ApiServiceProvider, private val outbox: OutboxRepository,
    private val payloadAdapter: JsonAdapter<ManualRatePayload>, private val receiptAdapter: JsonAdapter<ExchangeRateDto>) : ManualRateActions {
    private val guard = LedgerRequestGuard(provider)
    private val errors = NetworkErrorHandler({ provider.currentSession()?.serverUrl }, "ManualExchangeRate")

    override fun describeRate(row: OutboxRow): PendingManualRateSubmission? {
        val binding = guard.captureLogicalBinding() ?: return null
        if (row.type != PendingMutationType.SaveManualExchangeRate || row.ownerKey != binding.ownerKey ||
            row.ledgerId != binding.ledgerId || canonicalServerOriginOrNull(row.serverUrl) != canonicalServerOriginOrNull(binding.serverUrl)) return null
        val intent = runCatching { payloadAdapter.fromJson(row.payloadJson) }.getOrNull()
        val receipt = row.receiptJson?.let { runCatching { receiptAdapter.fromJson(it) }.getOrNull() }
        return PendingManualRateSubmission(row, intent, receipt?.takeIf { intent?.accepts(row, it) == true })
    }

    override fun observeRates(expectedBinding: LogicalSessionBinding): Flow<List<PendingManualRateSubmission>> =
        outbox.observeActiveByTypes(setOf(PendingMutationType.SaveManualExchangeRate), includeCompleted = true).map { rows ->
            if (guard.captureLogicalBinding() != expectedBinding) emptyList() else rows.mapNotNull(::describeRate)
        }

    override suspend fun exchangeRates(expectedBinding: LogicalSessionBinding, currencyCode: String?,
        homeCurrencyCode: String?, rateDate: String?): Result<List<ExchangeRateDto>> = errors.safeCall {
        guard.bindExact(expectedBinding).call { it.exchangeRates(currencyCode, homeCurrencyCode, rateDate, 365).items }.also { rows ->
            requireManualRate(rows.all { row -> validRateBaseline(row) &&
                (currencyCode == null || row.currencyCode == currencyCode) &&
                (homeCurrencyCode == null || row.homeCurrencyCode == homeCurrencyCode) &&
                (rateDate == null || row.rateDate == rateDate) }, "manual_rate_current_unverified")
            requireManualRate(rows.distinctBy { Triple(it.currencyCode, it.homeCurrencyCode, it.rateDate) }.size == rows.size,
                "manual_rate_current_unverified")
        }
    }

    override suspend fun enqueueRate(expectedBinding: LogicalSessionBinding, month: String,
        request: ExchangeRateRequestDto, originalPublicId: String?): Result<Long> = errors.safeCall {
        requireManualRate(ledgerRoleCanModify(provider.currentLedgerRole()), "permission_denied")
        val bound = guard.bindExact(expectedBinding)
        val payload = ManualRatePayload(1, month, originalPublicId, request)
        requireManualRate(payload.isSupported(), "manual_rate_original_unverified")
        requireManualRate(observeRates(expectedBinding).first().none {
            it.row.targetId == manualRateTarget(request) && !it.isConfirmed
        }, "manual_rate_submission_unresolved")
        outbox.enqueue(boundRequest = bound, intent = PendingMutationIntent(PendingMutationType.SaveManualExchangeRate,
            manualRateTarget(request), payloadAdapter.toJson(payload), request.expectedRowVersion, UUID.randomUUID().toString()),
            validateTargetRows = { rows -> requireManualRate(rows.none { it.status != PendingMutationStatus.Done }, "manual_rate_submission_unresolved") })
    }

    override suspend fun recoverRate(expectedBinding: LogicalSessionBinding, pending: PendingManualRateSubmission,
        drop: Boolean): Result<Unit> = errors.safeCall {
        val bound = guard.bindExact(expectedBinding)
        val original = observeRates(expectedBinding).first().firstOrNull { it.row.id == pending.row.id }
        requireManualRate(original?.row == pending.row, "manual_rate_submission_changed")
        requireNotNull(original)
        requireManualRate(if (drop) original.canDrop else original.canRetry && ledgerRoleCanModify(provider.currentLedgerRole()), "manual_rate_review_required")
        val changed = when (original.row.status) {
            PendingMutationStatus.Done -> outbox.discardCompletedOriginalSubmission(bound, original.row)
            PendingMutationStatus.Conflict -> outbox.resolveConflict(original.row.id, ConflictResolution.DropMine, bound)
            else -> outbox.resolveFailed(original.row.id, if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound)
        }
        requireManualRate(changed, "manual_rate_submission_changed")
    }
}

private fun requireManualRate(accepted: Boolean, code: String) {
    if (!accepted) throw RepositoryException(code, code)
}

private fun validRateBaseline(row: ExchangeRateDto): Boolean = row.rowVersion > 0 && row.publicId.isNotBlank() &&
    ManualRatePayload(1, row.rateDate.take(7), row.publicId, ExchangeRateRequestDto(row.currencyCode,
        row.homeCurrencyCode, row.rateDate, com.ticketbox.domain.model.canonicalManualExchangeRateOrNull(row.rateToHome).orEmpty(),
        "manual", row.rowVersion)).isSupported()
