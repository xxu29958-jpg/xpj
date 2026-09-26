package com.ticketbox.domain.model

data class BudgetHistoryPage(
    val ledgerId: String,
    val month: String,
    val items: List<BudgetRevision>,
    val nextBeforeVersion: Long?,
)

data class BudgetRevision(
    val rowVersion: Long,
    val changeKind: String,
    val recordedAt: String,
    val snapshot: BudgetArrangement,
)

data class BudgetArrangement(
    val homeCurrencyCode: String?,
    val totalAmountCents: Long,
    val nonMonthlyAmountCents: Long,
    val rolloverAmountCents: Long,
    val excludedCategories: List<String>,
    val categoryBudgets: List<BudgetCategoryArrangement>,
    val archived: Boolean,
)

data class BudgetCategoryArrangement(val category: String, val amountCents: Long)
