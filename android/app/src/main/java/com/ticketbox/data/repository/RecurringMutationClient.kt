package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonReader
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
import okio.Buffer

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
            rows.mapNotNull(::describeManualIntent)
        }
    }

    override fun describeManualIntent(row: OutboxRow): RecurringPendingIntent? {
        val binding = requestGuard.captureLogicalBinding() ?: return null
        val origin = canonicalServerOriginOrNull(binding.serverUrl) ?: return null
        if (row.type !in RECURRING_OUTBOX_TYPES || row.ownerKey != binding.ownerKey || row.ledgerId != binding.ledgerId ||
            canonicalServerOriginOrNull(row.serverUrl) != origin) return null
        return parsePendingIntent(row, createAdapter, updateAdapter)
    }

    override suspend fun recoverManualIntent(binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean): Result<Unit> =
        errorHandler.safeCall {
            val bound = requestGuard.bindExact(binding)
            val original = checkNotNull(describeManualIntent(row)) { "原提交不属于当前连接，请重新核对。" }
            check(drop || canModify()) { "当前角色为只读，无法修改账本。" }
            check(drop || original.canRetry) { RECURRING_ORIGINAL_UNSUPPORTED }
            val queue = checkNotNull(outbox) { "固定支出提交暂不可用，请重新打开应用。" }
            when (row.status) {
                PendingMutationStatus.Conflict -> if (drop) queue.resolveConflict(row.id, ConflictResolution.DropMine, bound)
                PendingMutationStatus.Failed -> queue.resolveFailed(row.id,
                    if (drop) FailedResolution.Drop else FailedResolution.Retry(), bound)
                else -> Unit
            }
            Unit
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
                hasSupportedIntent = true,
            )
        }
    }

    override suspend fun updateAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        baseline: RecurringItem,
        patch: RecurringItemPatch,
    ): Result<RecurringPendingIntent> {
        if (baseline.ledgerId != expectedBinding.ledgerId) return recurringValidationFailure("recurring_ledger_conflict")
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
                hasSupportedIntent = true,
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
    val parsed = runCatching {
        when (row.type) {
            PendingMutationType.CreateRecurringItem -> {
                val request = requireNotNull(createAdapter?.fromJson(row.payloadJson))
                original.copy(
                    merchant = request.merchant,
                    baselineAmountCents = request.baselineAmountCents,
                    nextExpectedDateChanged = true,
                    nextExpectedDate = request.nextExpectedDate,
                    homeCurrencyCode = request.homeCurrencyCode,
                    hasSupportedIntent = request.matchesOriginal(row),
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
                    hasSupportedIntent = request.matchesOriginal(row),
                )
            }
        }
    }.getOrElse { readLegacyRecurringSummary(row.payloadJson, original) }
    return parsed.copy(canRetry = parsed.hasSupportedIntent && row.status == PendingMutationStatus.Failed &&
        (row.lastError?.startsWith("max_attempts_exceeded(") == true ||
            row.lastError in setOf("client_upgrade_required", "runtime_version_mismatch")))
}

/** Read-only legacy summary; integers are read as Long, never through floating point or a new default. */
private fun readLegacyRecurringSummary(json: String, original: RecurringPendingIntent): RecurringPendingIntent = runCatching {
    var summary = original
    JsonReader.of(Buffer().writeUtf8(json)).use { reader ->
        reader.beginObject()
        while (reader.hasNext()) {
            val field = reader.nextName()
            if (reader.peek() == JsonReader.Token.NULL) {
                reader.nextNull<Unit>()
                if (field == "next_expected_date") summary = summary.copy(nextExpectedDateChanged = true)
                continue
            }
            summary = when (field) {
                "merchant" -> summary.copy(merchant = reader.nextString())
                "baseline_amount_cents" -> summary.copy(baselineAmountCents = reader.nextLong())
                "home_currency_code" -> summary.copy(homeCurrencyCode = reader.nextString())
                "next_expected_date" -> summary.copy(nextExpectedDateChanged = true, nextExpectedDate = reader.nextString())
                else -> { reader.skipValue(); summary }
            }
        }
        reader.endObject()
    }
    summary
}.getOrDefault(original)

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

private fun recurringValidationFailure(errorCode: String): Result<RecurringPendingIntent> {
    val message = when (errorCode) {
        "recurring_ledger_conflict" -> "这条固定支出不属于当前账本，请重新打开记录。"
        "recurring_currency_conflict" -> "原记录的币种尚未确认或已不匹配。已保留填写内容，请先核对原记录。"
        "recurring_command_owner_unavailable" -> "固定支出提交暂不可用，请重新打开应用；填写内容已保留。"
        else -> backendErrorUserMessage(errorCode, "未能保存固定支出，请核对填写内容。")
    }
    return Result.failure(RepositoryException(message = message, errorCode = errorCode))
}

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
