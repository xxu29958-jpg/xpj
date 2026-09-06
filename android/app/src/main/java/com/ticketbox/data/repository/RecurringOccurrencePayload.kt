package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException
import java.time.YearMonth

internal const val RECURRING_OCCURRENCE_PAYLOAD_REVISION = 1

@JsonClass(generateAdapter = true)
data class RecurringOccurrencePayload(
    val revision: Int,
    val seriesPublicId: String,
    val seriesLabel: String,
    val period: String,
    val homeCurrencyCode: String,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val paymentLabel: String?,
    val paymentAmountCents: Long?,
    val request: RecurringOccurrencePaymentRequestDto,
)

internal fun occurrenceTarget(seriesId: String, period: String): String = "recurring_occurrence:$seriesId:$period"

internal fun JsonAdapter<RecurringOccurrencePayload>.readSupportedOccurrence(json: String): RecurringOccurrencePayload? =
    try {
        fromJson(json)?.takeIf { it.isSupported() }
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    }

private fun RecurringOccurrencePayload.isSupported(): Boolean {
    val validPeriod = runCatching { YearMonth.parse(period).toString() == period }.getOrDefault(false)
    return revision == RECURRING_OCCURRENCE_PAYLOAD_REVISION && validPeriod && request.hasSupportedAction() &&
        seriesPublicId.isNotBlank() && request.expectedRowVersion >= 0 && request.expectedSeriesRowVersion > 0 &&
        originSessionGeneration.isNotBlank() && originBindingRevision.isNotBlank() &&
        CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode) != null
}

private fun RecurringOccurrencePaymentRequestDto.hasSupportedAction(): Boolean = when (action) {
    "link" -> !expensePublicId.isNullOrBlank() && (expectedExpenseRowVersion ?: 0) > 0
    "clear" -> expensePublicId == null && expectedExpenseRowVersion == null
    else -> false
}
