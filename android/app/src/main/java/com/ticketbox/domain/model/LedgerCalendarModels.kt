package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class LedgerCalendar(
    val ledgerId: String,
    val revision: Long,
    val timezoneName: String,
    val basis: String,
    val adoptedAt: String,
)
