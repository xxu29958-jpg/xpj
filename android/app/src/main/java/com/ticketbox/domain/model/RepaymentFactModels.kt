package com.ticketbox.domain.model

data class RepaymentFactList(
    val homeCurrencyCode: String,
    val items: List<DebtRepayment>,
)
