package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class CategoryStatsDto(
    val category: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long?,
    val count: Int,
)

@JsonClass(generateAdapter = true)
data class TagStatsDto(
    val tag: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long?,
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

interface StatsProjectionDto {
    val month: String
    val homeCurrencyCode: String
}

@JsonClass(generateAdapter = true)
data class MonthlyStatsDto(
    @param:Json(name = "home_currency_code")
    override val homeCurrencyCode: String,
    @param:Json(name = "missing_rates")
    val missingRates: List<MissingExchangeRateDto> = emptyList(),
    override val month: String,
    @param:Json(name = "total_amount_cents")
    val totalAmountCents: Long?,
    val count: Int,
    @param:Json(name = "by_category")
    val byCategory: List<CategoryStatsDto>,
    @param:Json(name = "by_tag")
    val byTag: List<TagStatsDto> = emptyList(),
) : StatsProjectionDto

@JsonClass(generateAdapter = true)
data class LifestyleStatsDto(
    @param:Json(name = "home_currency_code")
    override val homeCurrencyCode: String,
    @param:Json(name = "missing_rates")
    val missingRates: List<MissingExchangeRateDto> = emptyList(),
    override val month: String,
    @param:Json(name = "ai_subscription_amount_cents")
    val aiSubscriptionAmountCents: Long?,
    @param:Json(name = "digital_amount_cents")
    val digitalAmountCents: Long?,
    @param:Json(name = "max_expense")
    val maxExpense: ExpenseDto?,
    @param:Json(name = "recent_7_days_amount_cents")
    val recent7DaysAmountCents: Long?,
    @param:Json(name = "frequent_merchants")
    val frequentMerchants: List<FrequentMerchantDto>,
    @param:Json(name = "best_value_expenses")
    val bestValueExpenses: List<ExpenseDto> = emptyList(),
    @param:Json(name = "most_regretted_expenses")
    val mostRegrettedExpenses: List<ExpenseDto> = emptyList(),
) : StatsProjectionDto

@JsonClass(generateAdapter = true)
data class FrequentMerchantDto(
    val merchant: String,
    val count: Int,
    @param:Json(name = "amount_cents")
    val amountCents: Long?,
)
