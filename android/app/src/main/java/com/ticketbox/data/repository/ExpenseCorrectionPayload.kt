package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import java.io.IOException

/** Frozen command and original display context. Room owns the key and delivery state. */
@JsonClass(generateAdapter = true)
data class ExpenseCorrectionPayload(
    val revision: Int,
    val expenseId: Long,
    val originalMerchant: String?,
    val originalCurrencyCode: String,
    val originalAmountMinor: Long?,
    val homeCurrencyCode: String,
    val ownerKey: String,
    val ledgerId: String,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val request: ExpenseCorrectionRequestDto,
)

data class PendingExpenseCorrection(
    val row: OutboxRow,
    val intent: ExpenseCorrectionPayload?,
    /** Original decoded but inadmissible input is display-only; never a source for replay or new OCC. */
    val legacyRequest: ExpenseCorrectionRequestDto? = null,
) {
    val hasSupportedIntent: Boolean get() = intent != null
    val expenseId: Long? get() = parseExpenseTargetRef(row.targetId)?.toLongOrNull()
    val delivered: Boolean get() = hasSupportedIntent && row.status == PendingMutationStatus.Done
    val canRetry: Boolean get() = hasSupportedIntent && row.status == PendingMutationStatus.Failed &&
        row.lastError != "outbox_row_expired" && row.lastError != "correction_target_unavailable"
    val canDiscard: Boolean get() = row.status == PendingMutationStatus.Failed ||
        row.status == PendingMutationStatus.Conflict || (!hasSupportedIntent && row.status in setOf(PendingMutationStatus.Done, PendingMutationStatus.Pending))
}

data class ExpenseCorrectionObservation(
    val access: LedgerAccessContext?,
    val corrections: List<PendingExpenseCorrection>,
)

internal fun JsonAdapter<ExpenseCorrectionPayload>.readSupportedCorrection(row: OutboxRow): ExpenseCorrectionPayload? =
    readCorrectionJson(row.payloadJson)?.takeIf {
        it.completeOrigin() && it.matchesOriginalRow(row) && it.request.correctionAdmissionError() == null
    }

internal fun JsonAdapter<ExpenseCorrectionPayload>.readDisplayCorrection(row: OutboxRow): ExpenseCorrectionRequestDto? =
    readCorrectionJson(row.payloadJson)?.takeIf { it.matchesOriginalRow(row) }?.request

private fun ExpenseCorrectionPayload.completeOrigin(): Boolean =
    revision == 1 && expenseId > 0 && request.expectedRowVersion > 0 &&
        ownerKey.isNotBlank() && ledgerId.isNotBlank() && originalCurrencyCode.isNotBlank() && homeCurrencyCode.isNotBlank() &&
        (originalAmountMinor == null || originalAmountMinor >= 0) &&
        originSessionGeneration.isNotBlank() && originBindingRevision.isNotBlank()

private fun ExpenseCorrectionPayload.matchesOriginalRow(row: OutboxRow): Boolean =
    row.targetId == "expense:$expenseId" && request.expectedRowVersion == row.expectedRowVersion &&
        !row.idempotencyKey.isNullOrBlank() && ownerKey == row.ownerKey && ledgerId == row.ledgerId

internal fun <T> JsonAdapter<T>.readCorrectionJson(json: String): T? = try {
    fromJson(json)
} catch (_: JsonDataException) {
    null
} catch (_: IOException) {
    null
}
