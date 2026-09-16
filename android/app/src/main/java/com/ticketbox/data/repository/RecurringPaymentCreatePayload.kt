package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto

/** Explicit period-payment origin on the existing CreateExpense Outbox row. Not a second Writer. */
data class RecurringPaymentOrigin(
    val seriesPublicId: String,
    val period: String,
    val occurrenceRowVersion: Long? = null,
)

internal sealed class RecurringPaymentOriginLookup {
    data object Absent : RecurringPaymentOriginLookup()
    data class Found(val projection: ManualExpenseCreationProjection) : RecurringPaymentOriginLookup()
    data object Conflict : RecurringPaymentOriginLookup()
}

/** Bind leftover clientRef onto the existing CreateExpense row. Never enqueues. */
internal sealed class RecurringPaymentOriginAdopt {
    data object Bound : RecurringPaymentOriginAdopt()
    data object Missing : RecurringPaymentOriginAdopt()
    data object Conflict : RecurringPaymentOriginAdopt()
}

/** Admission result for the existing CreateExpense writer. Not a second command. */
internal sealed class ManualExpenseCreateAdmission {
    data class Accepted(val clientRef: String) : ManualExpenseCreateAdmission()
    data class ReviewRequired(val candidateClientRefs: List<String>) : ManualExpenseCreateAdmission()
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
    val retired: Boolean = false,
    val occurrenceRowVersion: Long? = null,
)

internal fun encodeManualCreatePayload(
    requestAdapter: JsonAdapter<ExpenseManualCreateRequestDto>,
    originAdapter: JsonAdapter<RecurringPaymentCreatePayload>?,
    request: ExpenseManualCreateRequestDto,
    origin: RecurringPaymentOrigin?,
    retired: Boolean = false,
): String {
    if (origin == null || originAdapter == null) return requestAdapter.toJson(request)
    return originAdapter.toJson(
        RecurringPaymentCreatePayload(
            request,
            origin.seriesPublicId,
            origin.period,
            retired,
            origin.occurrenceRowVersion,
        ),
    )
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

internal fun decodeRecurringPaymentPayload(
    originAdapter: JsonAdapter<RecurringPaymentCreatePayload>?,
    json: String,
): RecurringPaymentCreatePayload? {
    val stored = originAdapter?.let { runCatching { it.fromJson(json) }.getOrNull() } ?: return null
    if (stored.seriesPublicId.isBlank() || stored.period.isBlank()) return null
    return stored
}

internal fun decodeRecurringPaymentOrigin(
    originAdapter: JsonAdapter<RecurringPaymentCreatePayload>?,
    json: String,
): RecurringPaymentOrigin? {
    val stored = decodeRecurringPaymentPayload(originAdapter, json) ?: return null
    if (stored.retired) return null
    return RecurringPaymentOrigin(stored.seriesPublicId, stored.period, stored.occurrenceRowVersion)
}

internal fun RecurringPaymentCreatePayload.matchesOrigin(origin: RecurringPaymentOrigin): Boolean =
    seriesPublicId == origin.seriesPublicId && period == origin.period

internal fun RecurringPaymentCreatePayload.matchesActiveOrigin(origin: RecurringPaymentOrigin): Boolean =
    !retired && matchesOrigin(origin) && occurrenceRowVersion == origin.occurrenceRowVersion
