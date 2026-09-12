package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.ticketbox.domain.model.CurrencyReferenceRate

@JsonClass(generateAdapter = true)
data class ProjectionReferenceDto(
    @param:Json(name = "source_currency_code") val sourceCurrencyCode: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "rate_date") val rateDate: String,
) {
    fun toDomain() = CurrencyReferenceRate(sourceCurrencyCode, homeCurrencyCode, rateDate)
}
