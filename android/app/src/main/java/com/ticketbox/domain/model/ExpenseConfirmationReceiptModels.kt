package com.ticketbox.domain.model

data class ExpenseConfirmationReceipt(
    val id: Long,
    val publicId: String,
    val rowVersion: Long,
    val factRevision: Long,
    val status: String,
    val amountCents: Long,
    val homeCurrency: String,
    val originalCurrencyCode: String,
    val originalAmountMinor: Long?,
    val exchangeRateToCny: String?,
    val exchangeRateDate: String?,
    val exchangeRateSource: String?,
    val merchant: String?,
    val category: String,
    val accountingTime: ExpenseAccountingTime? = null,
    val confirmedAt: String?,
)
