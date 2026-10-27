package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class CategoryRuleDefinition(
    val keyword: String?,
    val category: String?,
    val enabled: Boolean?,
    val priority: Int?,
    @param:Json(name = "amount_min_cents")
    val amountMinCents: Long? = null,
    @param:Json(name = "amount_max_cents")
    val amountMaxCents: Long? = null,
    @param:Json(name = "source_contains")
    val sourceContains: String? = null,
    @param:Json(name = "tag_contains")
    val tagContains: String? = null,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String? = null,
)
