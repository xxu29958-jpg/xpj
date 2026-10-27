package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class ReferenceRate(
    val currencyCode: String,
    val homeCurrencyCode: String,
    val rateDate: String,
    val rateToHome: String,
    val source: String,
    val fetchedAt: String? = null,
    val verifiedThrough: String? = null,
)

data class ReferenceRateRequest(
    val homeCurrencyCode: String,
    val currencyCode: String? = null,
    val rateDate: String? = null,
)

data class ReferenceRates(
    val provider: String,
    val autoEnabled: Boolean,
    val syncState: String,
    val requestedDate: String? = null,
    val effective: ReferenceRate? = null,
    val items: List<ReferenceRate>,
)
