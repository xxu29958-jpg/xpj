package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto
import java.io.IOException

private const val DEBT_ADJUSTMENT_REVISION = 1

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
    val hasSupportedIntent: Boolean get() = intent != null
}

internal fun debtAdjustmentTarget(publicId: String): String = "debt:$publicId"

internal fun JsonAdapter<DebtAdjustmentPayload>.readSupportedDebtAdjustment(json: String): DebtAdjustmentPayload? =
    try {
        fromJson(json)?.takeIf {
            it.revision == DEBT_ADJUSTMENT_REVISION && it.subject.publicId.isNotBlank() &&
                CurrencyCode.fromStorageKeyOrNull(it.subject.homeCurrencyCode) != null &&
                it.originSessionGeneration.isNotBlank() && it.originBindingRevision.isNotBlank() &&
                it.request.expectedRowVersion > 0 && it.request.amountCents != 0L && it.request.reason.isNotBlank()
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
