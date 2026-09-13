package com.ticketbox.domain.model

data class BudgetCategoryBudget(
    val category: String,
    val amountCents: Long,
    val spentAmountCents: Long?,
    val remainingAmountCents: Long?,
    val overspentAmountCents: Long?,
)

data class BudgetExcludedCategory(
    val category: String,
    val amountCents: Long?,
    val count: Int,
)

data class BudgetMonthly(
    val ledgerId: String,
    val month: String,
    val configured: Boolean,
    val totalAmountCents: Long,
    val rolloverAmountCents: Long,
    val fixedAmountCents: Long?,
    val nonMonthlyAmountCents: Long,
    val flexBudgetCents: Long?,
    val spentAmountCents: Long?,
    val excludedAmountCents: Long?,
    val remainingAmountCents: Long?,
    val overspentAmountCents: Long?,
    val excludedCategories: List<String>,
    val excludedBreakdown: List<BudgetExcludedCategory>,
    val categoryBudgets: List<BudgetCategoryBudget>,
    val updatedAt: String?,
    val rowVersion: Long? = null,
    val homeCurrencyCode: String? = null,
    val missingCurrencyCodes: List<String> = emptyList(),
) {
    val availableAmountCents: Long = totalAmountCents + rolloverAmountCents
    val isOverBudget: Boolean = overspentAmountCents?.let { it > 0L } == true ||
        remainingAmountCents?.let { it < 0L } == true
    val spentPercent: Long? = spentAmountCents?.let { moneyPercent(it, availableAmountCents) }
    val spentProgress: Float? = spentAmountCents?.let { spent ->
        if (availableAmountCents > 0L) {
            (spent.toFloat() / availableAmountCents.toFloat()).coerceIn(0f, 1f)
        } else { 0f }
    }
}

enum class BudgetProgressStatus {
    Unknown,
    Unconfigured,
    ConfiguredWithoutProgress,
    Progress,
}

data class BudgetCategoryDraft(
    val category: String,
    val amountCents: Long,
)

data class BudgetMonthlyUpdate(
    val homeCurrencyCode: String,
    val expectedRowVersion: Long?,
    val totalAmountCents: Long,
    val nonMonthlyAmountCents: Long = 0,
    val rolloverAmountCents: Long = 0,
    val excludedCategories: List<String> = emptyList(),
    val categoryBudgets: List<BudgetCategoryDraft> = emptyList(),
)

data class BudgetAdviceResult(
    val advice: BudgetAdvice?,
    val homeCurrencyCode: String,
    val providerName: String,
    val reasonCode: String?,
)

data class BudgetAdvice(
    val summary: String,
    val suggestions: List<BudgetSuggestion>,
    val confidence: Double?,
)

data class BudgetSuggestion(
    val category: String?,
    val suggestedAmountCents: Long,
    val rationale: String,
)

fun BudgetMonthly.toBudgetProgressStatus(): BudgetProgressStatus = when {
    !configured -> BudgetProgressStatus.Unconfigured
    toBudgetProgress() == null -> BudgetProgressStatus.ConfiguredWithoutProgress
    else -> BudgetProgressStatus.Progress
}

fun BudgetMonthly.toBudgetProgress(): BudgetProgress? {
    if (!configured || homeCurrencyCode.isNullOrBlank()) return null
    val spent = spentAmountCents ?: return null
    val remaining = remainingAmountCents ?: return null
    val progress = spentProgress ?: return null
    val percent = spentPercent ?: return null
    val budget = availableAmountCents.takeIf { it > 0L } ?: return null
    return BudgetProgress(
        month = month,
        budgetCents = budget,
        spentCents = spent,
        remainingCents = remaining,
        progress = progress,
        percent = percent,
        overBudget = isOverBudget,
        homeCurrencyCode = homeCurrencyCode,
    )
}
