package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ReferenceRate(
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "rate_date") val rateDate: String,
    @param:Json(name = "rate_to_home") val rateToHome: String,
    val source: String,
    @param:Json(name = "fetched_at") val fetchedAt: String? = null,
    @param:Json(name = "verified_through") val verifiedThrough: String? = null,
)

@JsonClass(generateAdapter = true)
data class ReferenceRateRequest(
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "currency_code") val currencyCode: String? = null,
    @param:Json(name = "rate_date") val rateDate: String? = null,
)

@JsonClass(generateAdapter = true)
data class ReferenceRates(
    val provider: String,
    @param:Json(name = "auto_enabled") val autoEnabled: Boolean,
    @param:Json(name = "sync_state") val syncState: String,
    @param:Json(name = "requested_date") val requestedDate: String? = null,
    val effective: ReferenceRate? = null,
    val items: List<ReferenceRate>,
)
