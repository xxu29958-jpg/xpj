package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ExchangeRate(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "rate_date") val rateDate: String,
    @param:Json(name = "rate_to_cny") val rateToHome: String,
    val source: String,
    @param:Json(name = "created_at") val createdAt: String,
    @param:Json(name = "updated_at") val updatedAt: String,
    @param:Json(name = "row_version") val rowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class ExchangeRateRequest(
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "rate_date") val rateDate: String,
    @param:Json(name = "rate_to_cny") val rateToHome: String,
    val source: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
)
