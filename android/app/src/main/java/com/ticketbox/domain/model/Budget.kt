package com.ticketbox.domain.model

import kotlin.math.roundToInt

data class BudgetCategoryBudget(
    val category: String,
    val amountCents: Long,
    val spentAmountCents: Long,
    val remainingAmountCents: Long,
    val overspentAmountCents: Long,
)

data class BudgetExcludedCategory(
    val category: String,
    val amountCents: Long,
    val count: Int,
)

data class BudgetMonthly(
    val ledgerId: String,
    val month: String,
    val configured: Boolean,
    val totalAmountCents: Long,
    val rolloverAmountCents: Long,
    val fixedAmountCents: Long,
    val nonMonthlyAmountCents: Long,
    val flexBudgetCents: Long,
    val spentAmountCents: Long,
    val excludedAmountCents: Long,
    val remainingAmountCents: Long,
    val overspentAmountCents: Long,
    val excludedCategories: List<String>,
    val excludedBreakdown: List<BudgetExcludedCategory>,
    val categoryBudgets: List<BudgetCategoryBudget>,
    val updatedAt: String?,
    val rowVersion: Long? = null,
) {
    val availableAmountCents: Long = totalAmountCents + rolloverAmountCents
    val isOverBudget: Boolean = overspentAmountCents > 0L || remainingAmountCents < 0L
    val spentPercent: Int = if (availableAmountCents > 0L) {
        ((spentAmountCents.toDouble() / availableAmountCents.toDouble()) * 100).roundToInt()
    } else {
        0
    }
    val spentProgress: Float = if (availableAmountCents > 0L) {
        (spentAmountCents.toFloat() / availableAmountCents.toFloat()).coerceIn(0f, 1f)
    } else {
        0f
    }
}

data class BudgetCategoryDraft(
    val category: String,
    val amountCents: Long,
)

data class BudgetMonthlyUpdate(
    val totalAmountCents: Long,
    val nonMonthlyAmountCents: Long = 0,
    val rolloverAmountCents: Long = 0,
    val excludedCategories: List<String> = emptyList(),
    val categoryBudgets: List<BudgetCategoryDraft> = emptyList(),
)

fun BudgetMonthly.toBudgetProgress(): BudgetProgress? {
    val budget = availableAmountCents.takeIf { it > 0L } ?: return null
    return BudgetProgress(
        month = month,
        budgetCents = budget,
        spentCents = spentAmountCents,
        remainingCents = remainingAmountCents,
        progress = spentProgress,
        percent = spentPercent,
        overBudget = isOverBudget,
    )
}
