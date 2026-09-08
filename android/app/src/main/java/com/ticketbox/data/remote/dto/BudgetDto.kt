package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class BudgetCategoryRequestDto(
    val category: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
)

@JsonClass(generateAdapter = true)
data class BudgetMonthlyUpdateRequestDto(
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long?,
    @param:Json(name = "total_amount_cents")
    val totalAmountCents: Long,
    @param:Json(name = "non_monthly_amount_cents")
    val nonMonthlyAmountCents: Long = 0,
    @param:Json(name = "rollover_amount_cents")
    val rolloverAmountCents: Long = 0,
    @param:Json(name = "excluded_categories")
    val excludedCategories: List<String> = emptyList(),
    @param:Json(name = "category_budgets")
    val categoryBudgets: List<BudgetCategoryRequestDto> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class BudgetCategoryDto(
    val category: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    @param:Json(name = "spent_amount_cents")
    val spentAmountCents: Long?,
    @param:Json(name = "remaining_amount_cents")
    val remainingAmountCents: Long?,
    @param:Json(name = "overspent_amount_cents")
    val overspentAmountCents: Long?,
)

@JsonClass(generateAdapter = true)
data class BudgetExcludedCategoryDto(
    val category: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long?,
    val count: Int,
)

@JsonClass(generateAdapter = true)
data class BudgetMonthlyDto(
    @param:Json(name = "ledger_id")
    val ledgerId: String,
    val month: String,
    val configured: Boolean,
    @param:Json(name = "total_amount_cents")
    val totalAmountCents: Long,
    @param:Json(name = "rollover_amount_cents")
    val rolloverAmountCents: Long,
    @param:Json(name = "fixed_amount_cents")
    val fixedAmountCents: Long?,
    @param:Json(name = "non_monthly_amount_cents")
    val nonMonthlyAmountCents: Long,
    @param:Json(name = "flex_budget_cents")
    val flexBudgetCents: Long?,
    @param:Json(name = "spent_amount_cents")
    val spentAmountCents: Long?,
    @param:Json(name = "excluded_amount_cents")
    val excludedAmountCents: Long?,
    @param:Json(name = "remaining_amount_cents")
    val remainingAmountCents: Long?,
    @param:Json(name = "overspent_amount_cents")
    val overspentAmountCents: Long?,
    @param:Json(name = "excluded_categories")
    val excludedCategories: List<String>,
    @param:Json(name = "excluded_breakdown")
    val excludedBreakdown: List<BudgetExcludedCategoryDto>,
    @param:Json(name = "category_budgets")
    val categoryBudgets: List<BudgetCategoryDto>,
    @param:Json(name = "updated_at")
    val updatedAt: String?,
    @param:Json(name = "row_version")
    val rowVersion: Long? = null,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String? = null,
    @param:Json(name = "missing_currency_codes")
    val missingCurrencyCodes: List<String> = emptyList(),
)
