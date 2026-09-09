package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import com.ticketbox.data.remote.dto.RecurringOptionalDate
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.RecurringItem
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

/** Captures manual commands in the existing outbox before its dispatcher can send them. */
internal class RecurringMutationClient(
    private val requestGuard: LedgerRequestGuard,
    private val errorHandler: NetworkErrorHandler,
    private val canModify: () -> Boolean,
    private val outbox: OutboxRepository?,
    private val createAdapter: JsonAdapter<RecurringItemCreateRequestDto>?,
    private val updateAdapter: JsonAdapter<RecurringItemUpdateRequestDto>?,
) : RecurringManualMutationActions {
    override fun observePendingIntents(): Flow<List<RecurringPendingIntent>> {
        val outboxRef = outbox ?: return flowOf(emptyList())
        return outboxRef.observeActiveByTypes(RECURRING_OUTBOX_TYPES, includeCompleted = true).map { rows ->
            rows.map { row -> parsePendingIntent(row, createAdapter, updateAdapter) }
        }
    }

    override suspend fun createAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        draft: RecurringItemDraft,
    ): Result<RecurringPendingIntent> {
        validateDraft(draft)?.let { return recurringValidationFailure(it) }
        if (!canModify()) return recurringValidationFailure("permission_denied")
        val outboxRef = outbox ?: return recurringValidationFailure("recurring_command_owner_unavailable")
        val adapter = createAdapter ?: return recurringValidationFailure("recurring_command_owner_unavailable")
        val request = RecurringItemCreateRequestDto(
            merchant = draft.merchant.trim(),
            baselineAmountCents = draft.baselineAmountCents,
            nextExpectedDate = draft.nextExpectedDate?.trim()?.ifBlank { null },
            homeCurrencyCode = draft.homeCurrencyCode,
        )
        return errorHandler.safeCall {
            val bound = requestGuard.bindExact(expectedBinding)
            val key = UUID.randomUUID().toString()
            val targetId = "recurring_item_create:$key"
            outboxRef.enqueue(
                boundRequest = bound,
                intent = PendingMutationIntent(
                    type = PendingMutationType.CreateRecurringItem,
                    targetId = targetId,
                    payloadJson = adapter.toJson(request),
                    expectedRowVersion = 0,
                    idempotencyKey = key,
                ),
            )
            RecurringPendingIntent(
                kind = RecurringPendingKind.CREATE,
                targetId = targetId,
                idempotencyKey = key,
                merchant = request.merchant,
                baselineAmountCents = request.baselineAmountCents,
                nextExpectedDateChanged = true,
                nextExpectedDate = request.nextExpectedDate,
                homeCurrencyCode = request.homeCurrencyCode,
            )
        }
    }

    override suspend fun updateAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        baseline: RecurringItem,
        patch: RecurringItemPatch,
    ): Result<RecurringPendingIntent> {
        validatePatch(baseline, patch)?.let { return recurringValidationFailure(it) }
        if (!canModify()) return recurringValidationFailure("permission_denied")
        val outboxRef = outbox ?: return recurringValidationFailure("recurring_command_owner_unavailable")
        val adapter = updateAdapter ?: return recurringValidationFailure("recurring_command_owner_unavailable")
        val request = patch.toWireRequest(baseline.rowVersion)
        return errorHandler.safeCall {
            val bound = requestGuard.bindExact(expectedBinding)
            val key = UUID.randomUUID().toString()
            val targetId = "recurring_item:${baseline.publicId.trim()}"
            outboxRef.enqueue(
                boundRequest = bound,
                intent = PendingMutationIntent(
                    type = PendingMutationType.UpdateRecurringItem,
                    targetId = targetId,
                    payloadJson = adapter.toJson(request),
                    expectedRowVersion = baseline.rowVersion,
                    idempotencyKey = key,
                ),
            )
            RecurringPendingIntent(
                kind = RecurringPendingKind.UPDATE,
                targetId = targetId,
                idempotencyKey = key,
                publicId = baseline.publicId,
                merchant = request.merchant,
                baselineAmountCents = request.baselineAmountCents,
                nextExpectedDateChanged = request.nextExpectedDate.changed,
                nextExpectedDate = request.nextExpectedDate.value,
                homeCurrencyCode = request.homeCurrencyCode,
            )
        }
    }
}

private fun parsePendingIntent(
    row: OutboxRow,
    createAdapter: JsonAdapter<RecurringItemCreateRequestDto>?,
    updateAdapter: JsonAdapter<RecurringItemUpdateRequestDto>?,
): RecurringPendingIntent {
    val original = RecurringPendingIntent(
        kind = if (row.type == PendingMutationType.CreateRecurringItem) RecurringPendingKind.CREATE else RecurringPendingKind.UPDATE,
        targetId = row.targetId,
        idempotencyKey = row.idempotencyKey.orEmpty(),
        state = row.toRecurringPendingState(),
        publicId = row.targetId.removePrefix("recurring_item:")
            .takeIf { it != row.targetId && it.isNotBlank() },
    )
    // Unsupported originals remain visible and stored verbatim for explicit review.
    return runCatching {
        when (row.type) {
            PendingMutationType.CreateRecurringItem -> {
                val request = requireNotNull(createAdapter?.fromJson(row.payloadJson))
                original.copy(
                    merchant = request.merchant,
                    baselineAmountCents = request.baselineAmountCents,
                    nextExpectedDateChanged = true,
                    nextExpectedDate = request.nextExpectedDate,
                    homeCurrencyCode = request.homeCurrencyCode,
                )
            }
            else -> {
                val request = requireNotNull(updateAdapter?.fromJson(row.payloadJson))
                original.copy(
                    merchant = request.merchant,
                    baselineAmountCents = request.baselineAmountCents,
                    nextExpectedDateChanged = request.nextExpectedDate.changed,
                    nextExpectedDate = request.nextExpectedDate.value,
                    homeCurrencyCode = request.homeCurrencyCode,
                )
            }
        }
    }.getOrDefault(original)
}

private fun RecurringItemPatch.toWireRequest(rowVersion: Long): RecurringItemUpdateRequestDto =
    RecurringItemUpdateRequestDto(
        homeCurrencyCode = homeCurrencyCode,
        expectedRowVersion = rowVersion,
        merchant = merchant?.trim(),
        baselineAmountCents = baselineAmountCents,
        nextExpectedDate = RecurringOptionalDate(
            changed = nextExpectedDate.changed,
            value = nextExpectedDate.value?.trim()?.ifBlank { null },
        ),
    )

private fun validateDraft(draft: RecurringItemDraft): String? = when {
    draft.merchant.isBlank() -> "recurring_merchant_required"
    draft.baselineAmountCents <= 0 -> "amount_invalid"
    CurrencyCode.fromStorageKeyOrNull(draft.homeCurrencyCode) == null -> "recurring_currency_conflict"
    else -> null
}

private fun validatePatch(baseline: RecurringItem, patch: RecurringItemPatch): String? = when {
    baseline.publicId.isBlank() -> "recurring_item_not_found"
    baseline.rowVersion < 1 -> "state_conflict"
    patch.merchant != null && patch.merchant.isBlank() -> "recurring_merchant_required"
    patch.baselineAmountCents != null && patch.baselineAmountCents <= 0 -> "amount_invalid"
    CurrencyCode.fromStorageKeyOrNull(patch.homeCurrencyCode) == null || baseline.homeCurrencyCode != patch.homeCurrencyCode ->
        "recurring_currency_conflict"
    patch.merchant == null && patch.baselineAmountCents == null && !patch.nextExpectedDate.changed ->
        "recurring_item_no_changes"
    else -> null
}

private fun recurringValidationFailure(errorCode: String): Result<RecurringPendingIntent> =
    Result.failure(RepositoryException(message = errorCode, errorCode = errorCode))

private fun OutboxRow.toRecurringPendingState(): RecurringPendingState = when (status) {
    PendingMutationStatus.Done -> RecurringPendingState.DONE
    PendingMutationStatus.Conflict -> RecurringPendingState.CONFLICT
    PendingMutationStatus.Failed -> RecurringPendingState.FAILED
    else -> RecurringPendingState.WAITING
}

private val RECURRING_OUTBOX_TYPES = setOf(
    PendingMutationType.CreateRecurringItem,
    PendingMutationType.UpdateRecurringItem,
)
