package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import com.ticketbox.data.remote.dto.RecurringOptionalDate
import com.ticketbox.domain.model.RecurringItem
import java.io.IOException
import java.util.UUID
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.flow.map

/**
 * Manual fixed-expense command and durable-intent consumer. The public product
 * owner remains [RecurringRepository]; this helper keeps command/outbox concerns
 * out of its read and lifecycle surface.
 */
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
        val createJson = createAdapter ?: return flowOf(emptyList())
        val updateJson = updateAdapter ?: return flowOf(emptyList())
        return outboxRef.observeActiveByTypes(RECURRING_OUTBOX_TYPES).map { rows ->
            rows.mapNotNull { row -> parsePendingIntent(row, createJson, updateJson) }
        }
    }

    override suspend fun createAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        draft: RecurringItemDraft,
    ): Result<RecurringSaveOutcome> {
        validateDraft(draft)?.let { return recurringValidationFailure(it) }
        if (!canModify()) return readonlyFailure()
        val request = RecurringItemCreateRequestDto(
            merchant = draft.merchant.trim(),
            baselineAmountCents = draft.baselineAmountCents,
            nextExpectedDate = draft.nextExpectedDate?.trim()?.ifBlank { null },
        )
        return errorHandler.safeCall {
            val bound = requestGuard.bindExact(expectedBinding)
            val key = UUID.randomUUID().toString()
            val outboxRef = outbox
            val adapter = createAdapter
            if (outboxRef == null || adapter == null) {
                return@safeCall RecurringSaveOutcome.Synced(
                    bound.call { api -> api.createRecurringItem(request, key).toDomain() },
                )
            }
            try {
                RecurringSaveOutcome.Synced(
                    bound.call { api -> api.createRecurringItem(request, key).toDomain() },
                ) as RecurringSaveOutcome
            } catch (networkError: IOException) {
                bound.requireStillActive()
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
                RecurringSaveOutcome.Queued(
                    RecurringPendingIntent(
                        kind = RecurringPendingKind.CREATE,
                        targetId = targetId,
                        idempotencyKey = key,
                        merchant = request.merchant,
                        baselineAmountCents = request.baselineAmountCents,
                        nextExpectedDateChanged = true,
                        nextExpectedDate = request.nextExpectedDate,
                    ),
                ) as RecurringSaveOutcome
            }
        }
    }

    override suspend fun updateAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        baseline: RecurringItem,
        patch: RecurringItemPatch,
    ): Result<RecurringSaveOutcome> {
        validatePatch(baseline, patch)?.let { return recurringValidationFailure(it) }
        if (!canModify()) return readonlyFailure()
        val request = patch.toWireRequest(baseline.rowVersion)
        return errorHandler.safeCall {
            val bound = requestGuard.bindExact(expectedBinding)
            val key = UUID.randomUUID().toString()
            val targetId = "recurring_item:${baseline.publicId.trim()}"
            val outboxRef = outbox
            val adapter = updateAdapter
            if (outboxRef == null || adapter == null) {
                return@safeCall RecurringSaveOutcome.Synced(
                    bound.call { api ->
                        api.updateRecurringItem(baseline.publicId.trim(), request, key).toDomain()
                    },
                )
            }
            val queued = RecurringPendingIntent(
                kind = RecurringPendingKind.UPDATE,
                targetId = targetId,
                idempotencyKey = key,
                publicId = baseline.publicId,
                merchant = request.merchant,
                baselineAmountCents = request.baselineAmountCents,
                nextExpectedDateChanged = request.nextExpectedDate.changed,
                nextExpectedDate = request.nextExpectedDate.value,
            )
            suspend fun enqueue(): RecurringSaveOutcome {
                bound.requireStillActive()
                outboxRef.enqueue(
                    boundRequest = bound,
                    intent = PendingMutationIntent(
                        type = PendingMutationType.UpdateRecurringItem,
                        targetId = targetId,
                        payloadJson = adapter.toJson(request.copy(expectedRowVersion = 0)),
                        expectedRowVersion = baseline.rowVersion,
                        idempotencyKey = key,
                    ),
                )
                return RecurringSaveOutcome.Queued(queued)
            }
            if (outboxRef.activeForTarget(bound, targetId).isNotEmpty()) return@safeCall enqueue()
            try {
                RecurringSaveOutcome.Synced(
                    bound.call { api ->
                        api.updateRecurringItem(baseline.publicId.trim(), request, key).toDomain()
                    },
                ) as RecurringSaveOutcome
            } catch (networkError: IOException) {
                enqueue()
            }
        }
    }
}

private fun parsePendingIntent(
    row: OutboxRow,
    createAdapter: JsonAdapter<RecurringItemCreateRequestDto>,
    updateAdapter: JsonAdapter<RecurringItemUpdateRequestDto>,
): RecurringPendingIntent? {
    val key = row.idempotencyKey ?: return null
    return runCatching {
        when (row.type) {
            PendingMutationType.CreateRecurringItem -> {
                val request = requireNotNull(createAdapter.fromJson(row.payloadJson))
                RecurringPendingIntent(
                    kind = RecurringPendingKind.CREATE,
                    targetId = row.targetId,
                    idempotencyKey = key,
                    state = row.toRecurringPendingState(),
                    merchant = request.merchant,
                    baselineAmountCents = request.baselineAmountCents,
                    nextExpectedDateChanged = true,
                    nextExpectedDate = request.nextExpectedDate,
                )
            }
            PendingMutationType.UpdateRecurringItem -> {
                val request = requireNotNull(updateAdapter.fromJson(row.payloadJson))
                RecurringPendingIntent(
                    kind = RecurringPendingKind.UPDATE,
                    targetId = row.targetId,
                    idempotencyKey = key,
                    state = row.toRecurringPendingState(),
                    publicId = row.targetId.removePrefix("recurring_item:")
                        .takeIf { it != row.targetId && it.isNotBlank() },
                    merchant = request.merchant,
                    baselineAmountCents = request.baselineAmountCents,
                    nextExpectedDateChanged = request.nextExpectedDate.changed,
                    nextExpectedDate = request.nextExpectedDate.value,
                )
            }
            else -> null
        }
    }.getOrNull()
}

private fun RecurringItemPatch.toWireRequest(rowVersion: Long): RecurringItemUpdateRequestDto =
    RecurringItemUpdateRequestDto(
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
    draft.merchant.exceedsRecurringMerchantMaxLength() -> "recurring_merchant_too_long"
    draft.baselineAmountCents <= 0 -> "amount_invalid"
    else -> null
}

private fun validatePatch(baseline: RecurringItem, patch: RecurringItemPatch): String? = when {
    baseline.publicId.isBlank() -> "recurring_item_not_found"
    baseline.rowVersion < 1 -> "state_conflict"
    patch.merchant != null && patch.merchant.isBlank() -> "recurring_merchant_required"
    patch.merchant != null && patch.merchant.exceedsRecurringMerchantMaxLength() ->
        "recurring_merchant_too_long"
    patch.baselineAmountCents != null && patch.baselineAmountCents <= 0 -> "amount_invalid"
    patch.merchant == null && patch.baselineAmountCents == null && !patch.nextExpectedDate.changed ->
        "recurring_item_no_changes"
    else -> null
}

private fun readonlyFailure(): Result<RecurringSaveOutcome> =
    recurringValidationFailure("permission_denied")

private fun recurringValidationFailure(errorCode: String): Result<RecurringSaveOutcome> =
    Result.failure(RepositoryException(message = errorCode, errorCode = errorCode))

private fun OutboxRow.toRecurringPendingState(): RecurringPendingState = when (status) {
    PendingMutationStatus.Conflict -> RecurringPendingState.CONFLICT
    PendingMutationStatus.Failed -> RecurringPendingState.FAILED
    else -> RecurringPendingState.WAITING
}

private val RECURRING_OUTBOX_TYPES = setOf(
    PendingMutationType.CreateRecurringItem,
    PendingMutationType.UpdateRecurringItem,
)

private const val RECURRING_MERCHANT_MAX_LENGTH = 255

private fun String.exceedsRecurringMerchantMaxLength(): Boolean {
    val canonicalDisplay = trim()
    return canonicalDisplay.codePointCount(0, canonicalDisplay.length) > RECURRING_MERCHANT_MAX_LENGTH
}
