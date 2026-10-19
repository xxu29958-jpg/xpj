package com.ticketbox.domain.model

/** A reviewed payment component; native purchase and payer amounts are distinct facts. */
data class ExpenseFunding(val componentId: String, val accountPublicId: String, val accountRowVersion: Long,
    val expenseAmountMinor: Long, val accountAmountMinor: Long, val includedInOpening: Boolean = false,
    val expenseCurrencyCode: String? = null, val accountCurrencyCode: String? = null)
