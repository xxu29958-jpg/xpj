package com.ticketbox.domain.model

import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter

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

private fun Expense.ledgerLocalDate(zoneId: ZoneId): LocalDate? {
    val value = expenseTime ?: confirmedAt ?: createdAt
    return runCatching { Instant.parse(value).atZone(zoneId).toLocalDate() }
        .recoverCatching { OffsetDateTime.parse(value).toInstant().atZone(zoneId).toLocalDate() }
        .recoverCatching { LocalDate.parse(value.take(10)) }
        .getOrNull()
}
