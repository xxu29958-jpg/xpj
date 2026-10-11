package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ExpenseConfirmationReceiptDto(
    val id: Long,
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "fact_revision") val factRevision: Long,
    val status: String,
    @param:Json(name = "amount_cents") val amountCents: Long,
    @param:Json(name = "home_currency") val homeCurrency: String,
    @param:Json(name = "original_currency_code") val originalCurrencyCode: String,
    @param:Json(name = "original_amount_minor") val originalAmountMinor: Long?,
    @param:Json(name = "exchange_rate_to_cny") val exchangeRateToCny: String?,
    @param:Json(name = "exchange_rate_date") val exchangeRateDate: String?,
    @param:Json(name = "exchange_rate_source") val exchangeRateSource: String?,
    val merchant: String?,
    val category: String,
    @param:Json(name = "accounting_time") val accountingTime: ExpenseAccountingTimeDto? = null,
    @param:Json(name = "confirmed_at") val confirmedAt: String?,
)
