package com.ticketbox.domain.model

data class AmountConversion(
    val convertedAmount: String?,
    val references: List<ReferenceRate> = emptyList(),
)
