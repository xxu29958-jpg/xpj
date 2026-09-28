package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.ticketbox.domain.model.IncomeDefinition
import com.ticketbox.domain.model.IncomeHistoryPage
import com.ticketbox.domain.model.IncomeRevision

data class IncomeHistoryResponseDto(
    @Json(name = "ledger_id") val ledgerId: String,
    @Json(name = "public_id") val publicId: String,
    val items: List<IncomeRevisionDto>,
    @Json(name = "next_before_version") val nextBeforeVersion: Long?,
) {
    fun toDomain() = IncomeHistoryPage(items.map { IncomeRevision(it.rowVersion, it.changeKind, it.recordedAt,
        it.intentMonth, it.effectiveMonth, it.snapshot.toDomain()) }, nextBeforeVersion)
}

data class IncomeRevisionDto(
    @Json(name = "row_version") val rowVersion: Long,
    @Json(name = "change_kind") val changeKind: String,
    @Json(name = "recorded_at") val recordedAt: String,
    @Json(name = "intent_month") val intentMonth: String?,
    @Json(name = "effective_month") val effectiveMonth: String?,
    val snapshot: IncomeDefinitionDto,
)

data class IncomeDefinitionDto(
    val label: String,
    @Json(name = "source_type") val sourceType: String,
    val frequency: String,
    @Json(name = "income_month") val incomeMonth: String?,
    @Json(name = "amount_cents") val amountCents: Long,
    @Json(name = "home_currency_code") val homeCurrencyCode: String?,
    @Json(name = "pay_day") val payDay: Int,
    val status: String,
) {
    fun toDomain() = IncomeDefinition(label, sourceType, frequency, incomeMonth, amountCents, homeCurrencyCode, payDay, status)
}
