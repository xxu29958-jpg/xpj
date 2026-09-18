package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.ticketbox.data.local.PendingMutationStatus
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

internal enum class RecurringPaymentAdmissionBlock {
    MissingGeneration,
    DifferentGeneration,
}

internal sealed interface PeriodOriginAdmission {
    data object Empty : PeriodOriginAdmission
    data class Exact(val projection: ManualExpenseCreationProjection) : PeriodOriginAdmission
    data class DifferentGeneration(
        val projection: ManualExpenseCreationProjection,
        val occurrenceRowVersion: Long?,
    ) : PeriodOriginAdmission
    data object Conflict : PeriodOriginAdmission
}

/** Bind an existing CreateExpense row onto the current period origin. Never enqueues. */
internal sealed class RecurringPaymentOriginAdopt {
    data object Bound : RecurringPaymentOriginAdopt()
    data object Missing : RecurringPaymentOriginAdopt()
    data object Conflict : RecurringPaymentOriginAdopt()
    data class Blocked(
        val reason: RecurringPaymentAdmissionBlock,
        val occupant: RecurringPaymentPeriodOccupant.Occupied? = null,
    ) : RecurringPaymentOriginAdopt()
}

/** Admission result for the existing CreateExpense writer. Not a second command. */
internal sealed class ManualExpenseCreateAdmission {
    data class Accepted(val clientRef: String) : ManualExpenseCreateAdmission()
    data class ReviewRequired(val candidates: List<ManualExpenseCreationProjection>) : ManualExpenseCreateAdmission() {
        val candidateClientRefs: List<String>
            get() = candidates
                .mapNotNull { it.admittedClientRef() }
                .distinct()
                .sorted()
    }
    data class Blocked(
        val reason: RecurringPaymentAdmissionBlock,
        val occupant: RecurringPaymentPeriodOccupant.Occupied? = null,
    ) : ManualExpenseCreateAdmission()
}

internal sealed interface RecurringPaymentPeriodOccupant {
    data object Absent : RecurringPaymentPeriodOccupant
    data class Occupied(
        val clientRef: String,
        val occurrenceRowVersion: Long?,
        val acceptedExpenseId: Long? = null,
    ) : RecurringPaymentPeriodOccupant
    data object Conflict : RecurringPaymentPeriodOccupant
}

internal sealed class RecurringPaymentOriginRetire {
    data object Retired : RecurringPaymentOriginRetire()
    data object Missing : RecurringPaymentOriginRetire()
    data class CommandActive(val status: PendingMutationStatus) : RecurringPaymentOriginRetire()
    data object UnverifiedReceipt : RecurringPaymentOriginRetire()
    data object GenerationMismatch : RecurringPaymentOriginRetire()
}

internal fun periodOccupant(
    projection: ManualExpenseCreationProjection,
    occurrenceRowVersion: Long?,
): RecurringPaymentPeriodOccupant.Occupied? {
    val ref = projection.admittedClientRef()?.takeIf { it.isNotBlank() } ?: return null
    return RecurringPaymentPeriodOccupant.Occupied(ref, occurrenceRowVersion, projection.acceptedExpenseId)
}

internal fun classifyPeriodAdmission(
    active: List<Pair<RecurringPaymentCreatePayload, ManualExpenseCreationProjection>>,
    requested: RecurringPaymentOrigin,
): PeriodOriginAdmission {
    if (active.size > 1) return PeriodOriginAdmission.Conflict
    val (stored, projection) = active.singleOrNull() ?: return PeriodOriginAdmission.Empty
    if (stored.occurrenceRowVersion == requested.occurrenceRowVersion) {
        return PeriodOriginAdmission.Exact(projection)
    }
    return PeriodOriginAdmission.DifferentGeneration(projection, stored.occurrenceRowVersion)
}

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

internal fun RecurringPaymentCreatePayload.isSafeRetired(
    status: PendingMutationStatus,
    acceptedExpenseId: Long?,
): Boolean = retired && status == PendingMutationStatus.Done && (acceptedExpenseId ?: 0L) > 0L
