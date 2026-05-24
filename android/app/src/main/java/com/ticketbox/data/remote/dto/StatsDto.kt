package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class CategoryStatsDto(
    val category: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val count: Int,
)

data class TagStatsDto(
    val tag: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val count: Int,
)

data class CategoriesDto(
    val items: List<String>,
)

data class TagsDto(
    val items: List<String>,
)

data class MonthsDto(
    val items: List<String>,
)

data class MonthlyStatsDto(
    val month: String,
    @param:Json(name = "total_amount_cents")
    val totalAmountCents: Long,
    val count: Int,
    @param:Json(name = "by_category")
    val byCategory: List<CategoryStatsDto>,
    @param:Json(name = "by_tag")
    val byTag: List<TagStatsDto> = emptyList(),
)

data class LifestyleStatsDto(
    val month: String,
    @param:Json(name = "ai_subscription_amount_cents")
    val aiSubscriptionAmountCents: Long,
    @param:Json(name = "digital_amount_cents")
    val digitalAmountCents: Long,
    @param:Json(name = "max_expense")
    val maxExpense: ExpenseDto?,
    @param:Json(name = "recent_7_days_amount_cents")
    val recent7DaysAmountCents: Long,
    @param:Json(name = "frequent_merchants")
    val frequentMerchants: List<FrequentMerchantDto>,
)

data class FrequentMerchantDto(
    val merchant: String,
    val count: Int,
)
