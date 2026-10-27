package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

/** Advice premises are domain values; transport metadata never owns freshness or readiness. */
data class BudgetAdviceInputs(
    val month: String,
    val homeCurrencyCode: String,
    val breakdown: BudgetAdviceBreakdown,
    val missingRates: List<CurrencyProjectionGap>,
    val referenceRates: List<CurrencyReferenceRate> = emptyList(),
    val inputsFingerprint: String? = null,
    val undatedExpenseCount: Int? = null,
    val savedArrangement: MonthlyArrangement? = null,
    val isTrial: Boolean = false,
    val arrangementCurrencyCode: String? = null,
    val budgetDefinition: BudgetPlanDefinition? = null,
    val plannedTotalCents: Long? = null,
    val dataScope: BudgetAdviceDataScope? = null,
) {
    /** Reading time and the separately saved budget do not change what was sent to the advisor. */
    fun adviceBasis() = copy(budgetDefinition = null, plannedTotalCents = null,
        dataScope = dataScope?.copy(readAt = null))

    val readyForAdvice: Boolean get() = missingRates.isEmpty() && breakdown.monthlyIncomeCents != null &&
        breakdown.fixedExpensesCents != null && breakdown.spentAmountCents != null && breakdown.discretionaryCents != null
}

data class BudgetAdviceBreakdown(
    val monthlyIncomeCents: Long?,
    val fixedExpensesCents: Long?,
    val spentAmountCents: Long?,
    val savingsTargetCents: Long?,
    val reservedBufferCents: Long?,
    val discretionaryCents: Long?,
    val shortfallCents: Long? = null,
)

@JsonClass(generateAdapter = true)
data class MonthlyArrangement(
    @param:Json(name = "ledger_id") val ledgerId: String,
    val month: String,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "savings_target_cents") val savingsTargetCents: Long,
    @param:Json(name = "reserved_buffer_cents") val reservedBufferCents: Long,
    @param:Json(name = "row_version") val rowVersion: Long,
    @param:Json(name = "updated_at") val updatedAt: String,
)

data class BudgetPlanDefinition(
    val homeCurrencyCode: String?,
    val totalAmountCents: Long,
    val nonMonthlyAmountCents: Long,
    val rolloverAmountCents: Long,
    val excludedCategories: List<String>,
    val rowVersion: Long,
    val updatedAt: String,
)

data class BudgetAdviceDataScope(
    val readAt: String?,
    val historyFromMonth: String,
    val historyToMonth: String,
    val historyCategoryCount: Int,
)
