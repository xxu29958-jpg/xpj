package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class CategoryRuleDefinition(
    val keyword: String?,
    val category: String?,
    val enabled: Boolean?,
    val priority: Int?,
    val amountMinCents: Long? = null,
    val amountMaxCents: Long? = null,
    val sourceContains: String? = null,
    val tagContains: String? = null,
    val homeCurrencyCode: String? = null,
)
