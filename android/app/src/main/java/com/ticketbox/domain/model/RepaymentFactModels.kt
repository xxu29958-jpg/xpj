package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */


data class RepaymentFactList(
    val homeCurrencyCode: String,
    val items: List<DebtRepayment>,
)


