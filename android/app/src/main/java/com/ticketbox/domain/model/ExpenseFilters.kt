package com.ticketbox.domain.model

import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.YearMonth
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

fun filterConfirmedExpenses(
    expenses: List<Expense>,
    month: String,
    category: String,
    query: String = "",
    zoneId: ZoneId = ZoneId.systemDefault(),
): List<Expense> {
    val cleanMonth = month.trim()
    val cleanCategory = category.trim()
    val cleanQuery = query.trim().lowercase()
    val targetMonth = cleanMonth
        .takeIf { it.isNotBlank() }
        ?.let { value -> runCatching { YearMonth.parse(value) }.getOrNull() }
    if (cleanMonth.isNotBlank() && targetMonth == null) {
        return emptyList()
    }
    return expenses.filter { expense ->
        val expenseMonth = expense.ledgerLocalDate(zoneId)?.let { YearMonth.from(it) }
        val monthMatched = targetMonth == null || expenseMonth == targetMonth
        val categoryMatched = cleanCategory.isBlank() || expense.category == cleanCategory
        val queryMatched = cleanQuery.isBlank() || listOfNotNull(
            expense.merchant,
            expense.category,
            expense.note,
            expense.tags,
            expense.source,
        ).any { it.lowercase().contains(cleanQuery) }
        monthMatched && categoryMatched && queryMatched
    }
}

fun recentDailySpending(
    expenses: List<Expense>,
    days: Int = 7,
    referenceDate: LocalDate = LocalDate.now(ZoneId.systemDefault()),
    zoneId: ZoneId = ZoneId.systemDefault(),
): List<DailySpend> {
    require(days > 0) { "days must be greater than 0" }
    val startDate = referenceDate.minusDays((days - 1).toLong())
    val dates = (0 until days).map { offset -> startDate.plusDays(offset.toLong()) }
    val totals = dates.associateWith { 0L }.toMutableMap()

    expenses.forEach { expense ->
        val amount = expense.amountCents ?: return@forEach
        val date = expense.ledgerLocalDate(zoneId) ?: return@forEach
        if (date in startDate..referenceDate) {
            totals[date] = (totals[date] ?: 0L) + amount
        }
    }

    val labelFormatter = DateTimeFormatter.ofPattern("M/d")
    return dates.map { date ->
        DailySpend(
            date = date.toString(),
            label = labelFormatter.format(date),
            amountCents = totals[date] ?: 0L,
        )
    }
}

fun monthlySpendingComparison(
    expenses: List<Expense>,
    month: String,
    zoneId: ZoneId = ZoneId.systemDefault(),
): MonthComparison? {
    val currentMonth = runCatching { YearMonth.parse(month.trim()) }.getOrNull() ?: return null
    val previousMonth = currentMonth.minusMonths(1)
    var currentAmount = 0L
    var previousAmount = 0L

    expenses.forEach { expense ->
        val amount = expense.amountCents ?: return@forEach
        val expenseMonth = expense.ledgerLocalDate(zoneId)
            ?.let { YearMonth.from(it) }
            ?: return@forEach
        when (expenseMonth) {
            currentMonth -> currentAmount += amount
            previousMonth -> previousAmount += amount
        }
    }

    val delta = currentAmount - previousAmount
    val percentChange = if (previousAmount > 0L) {
        ((delta.toDouble() / previousAmount.toDouble()) * 100).roundToInt()
    } else {
        null
    }
    return MonthComparison(
        currentMonth = currentMonth.toString(),
        previousMonth = previousMonth.toString(),
        currentAmountCents = currentAmount,
        previousAmountCents = previousAmount,
        deltaAmountCents = delta,
        percentChange = percentChange,
    )
}

fun monthlyBudgetProgress(
    stats: MonthlyStats?,
    budgetCents: Long?,
): BudgetProgress? {
    val budget = budgetCents?.takeIf { it > 0L } ?: return null
    val monthlyStats = stats ?: return null
    val spent = monthlyStats.totalAmountCents
    val progress = (spent.toFloat() / budget.toFloat()).coerceAtLeast(0f)
    return BudgetProgress(
        month = monthlyStats.month,
        budgetCents = budget,
        spentCents = spent,
        remainingCents = budget - spent,
        progress = progress.coerceIn(0f, 1f),
        percent = (progress * 100).roundToInt(),
        overBudget = spent > budget,
    )
}

private fun Expense.ledgerLocalDate(zoneId: ZoneId): LocalDate? {
    val value = expenseTime ?: confirmedAt ?: createdAt
    return runCatching { Instant.parse(value).atZone(zoneId).toLocalDate() }
        .recoverCatching { OffsetDateTime.parse(value).toInstant().atZone(zoneId).toLocalDate() }
        .recoverCatching { LocalDate.parse(value.take(10)) }
        .getOrNull()
}
