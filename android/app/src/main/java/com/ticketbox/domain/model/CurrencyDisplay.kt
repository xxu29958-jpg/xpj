package com.ticketbox.domain.model

data class CurrencyDisplay(
    val homeCurrency: CurrencyCode = FxContract.HomeCurrency,
) {
    companion object {
        val Base: CurrencyDisplay = CurrencyDisplay()
    }
}
