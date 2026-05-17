package com.ticketbox.domain.model

object FxContract {
    /**
     * Client fallback for legacy/local rows before the backend response provides `home_currency`.
     * The backend remains the only authority for FX conversion and home amount calculation.
     */
    val HomeCurrency: CurrencyCode = CurrencyCode.CNY

    const val StatusReady = "ready"
    const val StatusPending = "pending"
    const val SourceBase = "base"
    const val BaseRateToHome = "1"
}
