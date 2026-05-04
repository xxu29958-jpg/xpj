package com.ticketbox.domain.model

fun filterConfirmedExpenses(
    expenses: List<Expense>,
    month: String,
    category: String,
): List<Expense> {
    val cleanMonth = month.trim()
    val cleanCategory = category.trim()
    return expenses.filter { expense ->
        val timeKey = expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt
        val monthMatched = cleanMonth.isBlank() || timeKey.startsWith(cleanMonth)
        val categoryMatched = cleanCategory.isBlank() || expense.category == cleanCategory
        monthMatched && categoryMatched
    }
}
