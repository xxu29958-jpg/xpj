package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import java.io.IOException
import java.time.YearMonth

internal const val RECURRING_OCCURRENCE_PAYLOAD_REVISION = 2

@JsonClass(generateAdapter = true)
data class RecurringOccurrencePayload(
    val revision: Int,
    val seriesPublicId: String,
    val seriesLabel: String,
    val period: String,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val paymentLabel: String?,
    val paymentAmountCents: Long?,
    val request: RecurringOccurrencePaymentRequestDto,
    val paymentCurrencyCode: String? = null,
)

internal fun occurrenceTarget(seriesId: String, period: String): String = "recurring_occurrence:$seriesId:$period"

internal fun JsonAdapter<RecurringOccurrencePayload>.readSupportedOccurrence(json: String): RecurringOccurrencePayload? =
    try {
        fromJson(json)?.takeIf { it.isSupported() }?.let {
            // Revision 1 captured the display default, not the payment's currency.
            // Its association command is still valid; never reinterpret its raw amount.
            if (it.revision == 1) it.copy(paymentCurrencyCode = null) else it
        }
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    }

private fun RecurringOccurrencePayload.isSupported(): Boolean {
    val validPeriod = runCatching { YearMonth.parse(period).toString() == period }.getOrDefault(false)
    return revision in 1..RECURRING_OCCURRENCE_PAYLOAD_REVISION && validPeriod && request.hasSupportedAction() &&
        seriesPublicId.isNotBlank() && request.expectedRowVersion >= 0 && request.expectedSeriesRowVersion > 0 &&
        originSessionGeneration.isNotBlank() && originBindingRevision.isNotBlank()
}

internal fun RecurringOccurrencePayload.matchesOriginal(row: OutboxRow): Boolean =
    !row.idempotencyKey.isNullOrBlank() && row.targetId == occurrenceTarget(seriesPublicId, period) &&
        row.expectedRowVersion == request.expectedRowVersion

internal fun RecurringOccurrencePayload.acceptsReceipt(receipt: RecurringOccurrenceDto): Boolean =
    receipt.seriesPublicId == seriesPublicId && receipt.period == period &&
        receipt.seriesRowVersion == request.expectedSeriesRowVersion &&
        receipt.rowVersion == request.expectedRowVersion + 1 &&
        receipt.expensePublicId == request.expensePublicId &&
        receipt.state == (if (request.action == "link") "fulfilled" else "unfulfilled")

private fun RecurringOccurrencePaymentRequestDto.hasSupportedAction(): Boolean = when (action) {
    "link" -> !expensePublicId.isNullOrBlank() && (expectedExpenseRowVersion ?: 0) > 0
    "clear" -> expensePublicId == null && expectedExpenseRowVersion == null
    else -> false
}
