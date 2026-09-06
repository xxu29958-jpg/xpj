package com.ticketbox.data.repository

import com.squareup.moshi.JsonAdapter
import com.squareup.moshi.JsonClass
import com.squareup.moshi.JsonDataException
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
import com.ticketbox.domain.model.CurrencyCode
import java.io.IOException
import java.time.YearMonth

internal const val INCOME_PLAN_EDIT_PAYLOAD_REVISION = 1

@JsonClass(generateAdapter = true)
data class IncomePlanEditPayload(
    val revision: Int,
    val planPublicId: String,
    val originalLabel: String,
    val originalAmountCents: Long,
    val homeCurrencyCode: String,
    val originSessionGeneration: String,
    val originBindingRevision: String,
    val request: IncomePlanUpdateRequestDto,
)

data class PendingIncomePlanEdit(val row: OutboxRow, val intent: IncomePlanEditPayload?)

internal fun incomePlanTarget(publicId: String): String = "income_plan:$publicId"

internal fun JsonAdapter<IncomePlanEditPayload>.readSupportedIncomeEdit(json: String): IncomePlanEditPayload? =
    try {
        fromJson(json)?.takeIf { it.isSupported() }
    } catch (_: JsonDataException) {
        null
    } catch (_: IOException) {
        null
    }

private fun IncomePlanEditPayload.isSupported(): Boolean {
    val month = runCatching { YearMonth.parse(request.intentMonth).toString() == request.intentMonth }.getOrDefault(false)
    return revision == INCOME_PLAN_EDIT_PAYLOAD_REVISION && month && planPublicId.isNotBlank() &&
        originalLabel.isNotBlank() && originalAmountCents >= 0 && request.expectedRowVersion == 0L &&
        originSessionGeneration.isNotBlank() && originBindingRevision.isNotBlank() &&
        CurrencyCode.fromStorageKeyOrNull(homeCurrencyCode) != null
}
