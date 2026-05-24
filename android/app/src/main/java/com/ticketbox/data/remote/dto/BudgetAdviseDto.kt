package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * v1.1 budget advisor DTOs. Mirrors
 * `backend/app/schemas/_budget_advisor.py`. The advice round-trip is
 * one-shot per AI call; nothing here is persisted on device.
 */
data class DiscretionaryResponseDto(
    @param:Json(name = "monthly_income_cents") val monthlyIncomeCents: Long,
    @param:Json(name = "fixed_expenses_cents") val fixedExpensesCents: Long,
    @param:Json(name = "savings_target_cents") val savingsTargetCents: Long,
    @param:Json(name = "reserved_buffer_cents") val reservedBufferCents: Long,
    @param:Json(name = "discretionary_cents") val discretionaryCents: Long,
)

data class BudgetAdviseRequestDto(
    val month: String,
    val timezone: String? = null,
)

data class BudgetSuggestionDto(
    val category: String?,
    @param:Json(name = "suggested_amount_cents") val suggestedAmountCents: Long,
    val rationale: String,
)

data class BudgetAdviceDto(
    val summary: String,
    val suggestions: List<BudgetSuggestionDto>,
    val confidence: Double?,
)

data class BudgetAdviseResponseDto(
    val advice: BudgetAdviceDto?,
    @param:Json(name = "provider_name") val providerName: String,
)
