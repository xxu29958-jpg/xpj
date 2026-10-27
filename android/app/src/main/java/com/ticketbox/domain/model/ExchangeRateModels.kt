package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class ExchangeRate(
    val publicId: String,
    val currencyCode: String,
    val homeCurrencyCode: String,
    val rateDate: String,
    val rateToHome: String,
    val source: String,
    val createdAt: String,
    val updatedAt: String,
    val rowVersion: Long,
)

data class ExchangeRateRequest(
    val currencyCode: String,
    val homeCurrencyCode: String,
    val rateDate: String,
    val rateToHome: String,
    val source: String,
    val expectedRowVersion: Long,
)
