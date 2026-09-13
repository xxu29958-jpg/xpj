package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import java.io.IOException

private const val DEBT_ADJUSTMENT_REVISION = 1
internal const val DEBT_ADJUSTMENT_NEGATIVE_REMAINING = "debt_adjustment_negative_remaining"

/** The request includes its original OCC; replay must never replace it with a refreshed token. */
@JsonClass(generateAdapter = true)
data class DebtAdjustmentPayload(
    val revision: Int,
    override val subject: DebtWriteSubject,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val request: DebtAdjustmentCreateRequestDto,
) : DebtWriteIntent {
    override val amountCents: Long get() = request.amountCents
    override val expectedRowVersion: Long get() = request.expectedRowVersion
}

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

internal fun OutboxRow.describeDebtAdjustment(adapter: JsonAdapter<DebtAdjustmentPayload>): PendingDebtWrite {
    val payload = adapter.readSupportedDebtAdjustment(payloadJson)?.takeIf {
        targetId == debtWriteTarget(it.subject.publicId) && expectedRowVersion == it.request.expectedRowVersion &&
            !idempotencyKey.isNullOrBlank()
    }
    return PendingDebtWrite(this, payload)
}

/** The backend strips Python whitespace after validating the wire string's code-point length. */
internal fun trimDebtAdjustmentReason(reason: String): String = reason.trim { it.isWhitespace() || it == '\u0085' }

internal fun isDebtAdjustmentReasonValid(reason: String): Boolean =
    reason.codePointCount(0, reason.length) <= 500 && trimDebtAdjustmentReason(reason).isNotEmpty()

/** Compare the decrease against a known nonnegative balance without adding signed money. */
internal fun isDebtAdjustmentWithinBalance(amountCents: Long, remainingAmountCents: Long): Boolean =
    amountCents >= 0L || (remainingAmountCents >= 0L && amountCents >= -remainingAmountCents)
