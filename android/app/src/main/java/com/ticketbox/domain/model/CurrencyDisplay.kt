package com.ticketbox.domain.model

data class CurrencyDisplay(
    val homeCurrency: CurrencyCode,
) {
    companion object {
        val LegacyFallback: CurrencyDisplay =
            CurrencyDisplay(FxContract.LegacyHomeCurrencyFallback)
    }
}
