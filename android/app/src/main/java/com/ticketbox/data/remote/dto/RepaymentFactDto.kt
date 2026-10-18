package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class RepaymentVoidFactDto(
    @param:Json(name = "public_id") val publicId: String,
    val reason: String,
    @param:Json(name = "created_at") val createdAt: String,
)

@JsonClass(generateAdapter = true)
data class RepaymentFactDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "amount_cents") val amountCents: Long,
    @param:Json(name = "paid_at") val paidAt: String?,
    @param:Json(name = "created_at") val createdAt: String,
    val status: String,
    @param:Json(name = "void_fact") val voidFact: RepaymentVoidFactDto? = null,
    @param:Json(name = "original_currency_code") val originalCurrencyCode: String? = null,
    @param:Json(name = "original_amount_minor") val originalAmountMinor: Long? = null,
    @param:Json(name = "exchange_rate_to_cny") val exchangeRateToCny: String? = null,
    @param:Json(name = "exchange_rate_date") val exchangeRateDate: String? = null,
    @param:Json(name = "exchange_rate_source") val exchangeRateSource: String? = null,
    @param:Json(name = "accounting_time") val accountingTime: ExpenseAccountingTimeDto? = null,
)

@JsonClass(generateAdapter = true)
data class RepaymentFactListDto(
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    val items: List<RepaymentFactDto>,
)
