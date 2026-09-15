package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto

/** Explicit period-payment origin on the existing CreateExpense Outbox row. Not a second Writer. */
data class RecurringPaymentOrigin(
    val seriesPublicId: String,
    val period: String,
)

internal sealed class RecurringPaymentOriginLookup {
    data object Absent : RecurringPaymentOriginLookup()
    data class Found(val projection: ManualExpenseCreationProjection) : RecurringPaymentOriginLookup()
    data object Conflict : RecurringPaymentOriginLookup()
}

/** Admission result for the existing CreateExpense writer. Not a second command. */
internal sealed class ManualExpenseCreateAdmission {
    data class Accepted(val clientRef: String) : ManualExpenseCreateAdmission()
}

/** N-1 SavedState left by RecurringPeriodPaymentSession. Not a second Writer. */
@JsonClass(generateAdapter = true)
internal data class LegacyPeriodPaymentSession(
    val binding: LogicalSessionBinding,
    val seriesPublicId: String,
    val period: String,
    val clientRef: String,
    val merchant: String,
    val obligationCurrencyCode: String? = null,
    val plannedAmountCents: Long? = null,
    val ledgerHomeCurrencyCode: String? = null,
    val category: String? = null,
    val note: String? = null,
    val capturedAmountCents: Long? = null,
    val admitted: Boolean = false,
)

@JsonClass(generateAdapter = true)
data class RecurringPaymentCreatePayload(
    val request: ExpenseManualCreateRequestDto,
    val seriesPublicId: String,
    val period: String,
)

internal fun encodeManualCreatePayload(
    requestAdapter: JsonAdapter<ExpenseManualCreateRequestDto>,
    originAdapter: JsonAdapter<RecurringPaymentCreatePayload>?,
    request: ExpenseManualCreateRequestDto,
    origin: RecurringPaymentOrigin?,
): String {
    if (origin == null || originAdapter == null) return requestAdapter.toJson(request)
    return originAdapter.toJson(RecurringPaymentCreatePayload(request, origin.seriesPublicId, origin.period))
}

internal fun decodeManualCreateRequest(
    requestAdapter: JsonAdapter<ExpenseManualCreateRequestDto>,
    originAdapter: JsonAdapter<RecurringPaymentCreatePayload>?,
    json: String,
): ExpenseManualCreateRequestDto? {
    originAdapter?.let { adapter ->
        runCatching { adapter.fromJson(json) }.getOrNull()?.request?.let { return it }
    }
    return runCatching { requestAdapter.fromJson(json) }.getOrNull()
}

internal fun decodeRecurringPaymentOrigin(
    originAdapter: JsonAdapter<RecurringPaymentCreatePayload>?,
    json: String,
): RecurringPaymentOrigin? {
    val stored = originAdapter?.let { runCatching { it.fromJson(json) }.getOrNull() } ?: return null
    if (stored.seriesPublicId.isBlank() || stored.period.isBlank()) return null
    return RecurringPaymentOrigin(stored.seriesPublicId, stored.period)
}
