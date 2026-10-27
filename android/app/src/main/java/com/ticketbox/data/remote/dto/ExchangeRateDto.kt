package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class ExchangeRateRequestDto(
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "rate_date") val rateDate: String,
    @param:Json(name = "rate_to_cny") val rateToHome: String,
    val source: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class ExchangeRateDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "rate_date") val rateDate: String,
    @param:Json(name = "rate_to_cny") val rateToHome: String,
    val source: String,
    @param:Json(name = "created_at") val createdAt: String,
    @param:Json(name = "updated_at") val updatedAt: String,
    @param:Json(name = "row_version") val rowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class ExchangeRateListDto(val items: List<ExchangeRateDto>)

@JsonClass(generateAdapter = true)
data class BudgetAdviceInputsDto(
    val month: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    val breakdown: DiscretionaryResponseDto,
    @param:Json(name = "missing_rates") val missingRates: List<MissingExchangeRateDto>,
    @param:Json(name = "reference_rates") val referenceRates: List<ProjectionReferenceDto> = emptyList(),
    @param:Json(name = "inputs_fingerprint") val inputsFingerprint: String? = null,
    @param:Json(name = "undated_expense_count")
    val undatedExpenseCount: Int? = null,
    @param:Json(name = "saved_arrangement") val savedArrangement: MonthlyArrangementDto? = null,
    @param:Json(name = "is_trial") val isTrial: Boolean = false,
    @param:Json(name = "arrangement_currency_code") val arrangementCurrencyCode: String? = null,
    @param:Json(name = "budget_definition") val budgetDefinition: BudgetPlanDefinitionDto? = null,
    @param:Json(name = "planned_total_cents") val plannedTotalCents: Long? = null,
    @param:Json(name = "data_scope") val dataScope: BudgetAdviceDataScopeDto? = null,
)

@JsonClass(generateAdapter = true)
data class BudgetPlanDefinitionDto(
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String?,
    @param:Json(name = "total_amount_cents") val totalAmountCents: Long,
    @param:Json(name = "non_monthly_amount_cents") val nonMonthlyAmountCents: Long,
    @param:Json(name = "rollover_amount_cents") val rolloverAmountCents: Long,
    @param:Json(name = "excluded_categories") val excludedCategories: List<String>,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "updated_at") val updatedAt: String,
)

@JsonClass(generateAdapter = true)
data class BudgetAdviceDataScopeDto(
    @param:Json(name = "read_at") val readAt: String?,
    @param:Json(name = "history_from_month") val historyFromMonth: String,
    @param:Json(name = "history_to_month") val historyToMonth: String,
    @param:Json(name = "history_category_count") val historyCategoryCount: Int,
)

@JsonClass(generateAdapter = true)
data class MissingExchangeRateDto(
    @param:Json(name = "source_currency_code") val sourceCurrencyCode: String?,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "rate_date") val rateDate: String?,
)
