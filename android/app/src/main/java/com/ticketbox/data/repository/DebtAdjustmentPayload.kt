package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Debt
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import com.ticketbox.data.local.PendingMutationStatus
import java.io.IOException

private const val DEBT_ADJUSTMENT_REVISION = 1
internal const val DEBT_ADJUSTMENT_NEGATIVE_REMAINING = "debt_adjustment_negative_remaining"

@JsonClass(generateAdapter = true)
data class DebtAdjustmentSubject(val publicId: String, val label: String?, val homeCurrencyCode: String)

/** The request includes its original OCC; replay must never replace it with a refreshed token. */
@JsonClass(generateAdapter = true)
data class DebtAdjustmentPayload(
    val revision: Int,
    val subject: DebtAdjustmentSubject,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val request: DebtAdjustmentCreateRequestDto,
)

data class PendingDebtAdjustment(val row: OutboxRow, val intent: DebtAdjustmentPayload?) {
    val isTerminal: Boolean get() = row.status == PendingMutationStatus.Done || row.status == PendingMutationStatus.Abandoned
    val isUnresolved: Boolean get() = row.status in setOf(PendingMutationStatus.Pending,
        PendingMutationStatus.InFlight, PendingMutationStatus.Failed, PendingMutationStatus.Conflict)
    val hasSupportedIntent: Boolean get() = intent != null
    val reductionRejected: Boolean
        get() = row.status == PendingMutationStatus.Failed && row.lastError == DEBT_ADJUSTMENT_NEGATIVE_REMAINING
    val canRetry: Boolean
        get() = row.status == PendingMutationStatus.Failed && hasSupportedIntent && !reductionRejected &&
            row.lastError?.startsWith("outbox_row_expired") != true
}

internal fun debtAdjustmentTarget(publicId: String): String = "debt:$publicId"

internal fun JsonAdapter<DebtAdjustmentPayload>.readSupportedDebtAdjustment(json: String): DebtAdjustmentPayload? =
    try {
        fromJson(json)?.takeIf {
            it.revision == DEBT_ADJUSTMENT_REVISION && it.subject.publicId.isNotBlank() &&
                CurrencyCode.fromStorageKeyOrNull(it.subject.homeCurrencyCode) != null &&
                it.originSessionGeneration.isNotBlank() && it.originBindingRevision.isNotBlank() &&
                it.request.expectedRowVersion > 0 && it.request.amountCents != 0L && isDebtAdjustmentReasonValid(it.request.reason)
        }
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    }

internal fun OutboxRow.describeDebtAdjustment(adapter: JsonAdapter<DebtAdjustmentPayload>): PendingDebtAdjustment {
    val payload = adapter.readSupportedDebtAdjustment(payloadJson)?.takeIf {
        targetId == debtAdjustmentTarget(it.subject.publicId) && expectedRowVersion == it.request.expectedRowVersion &&
            !idempotencyKey.isNullOrBlank()
    }
    return PendingDebtAdjustment(this, payload)
}

/** The backend strips Python whitespace after validating the wire string's code-point length. */
internal fun trimDebtAdjustmentReason(reason: String): String = reason.trim { it.isWhitespace() || it == '\u0085' }

internal fun isDebtAdjustmentReasonValid(reason: String): Boolean =
    reason.codePointCount(0, reason.length) <= 500 && trimDebtAdjustmentReason(reason).isNotEmpty()

/** Compare the decrease against a known nonnegative balance without adding signed money. */
internal fun isDebtAdjustmentWithinBalance(amountCents: Long, remainingAmountCents: Long): Boolean =
    amountCents >= 0L || (remainingAmountCents >= 0L && amountCents >= -remainingAmountCents)

/** Actual bound Room state, with terminal arrivals used only to invalidate canonical queries. */
data class DebtAdjustmentObservation(
    val binding: LogicalSessionBinding?,
    val adjustments: List<PendingDebtAdjustment>,
    val initial: Boolean,
    val newlyTerminal: List<PendingDebtAdjustment>,
) {
    val requiresRefresh: Boolean get() = initial || newlyTerminal.isNotEmpty()
    val unresolvedTargetIds: Set<String> get() = adjustments.filter { it.isUnresolved }.mapTo(mutableSetOf()) { it.row.targetId }

    /** Call only for a canonical query started after this observation; this does not prove freshness. */
    fun acceptsCanonical(debt: Debt): Boolean = adjustments.filter { it.row.targetId == debtAdjustmentTarget(debt.publicId) }
        .all { pending ->
            when (pending.row.status) {
                PendingMutationStatus.Done -> debt.rowVersion > (pending.row.expectedRowVersion ?: Long.MAX_VALUE)
                PendingMutationStatus.Abandoned -> pending.row.expectedRowVersion?.let { debt.rowVersion >= it } ?: true
                else -> !pending.isUnresolved
            }
        }
}
