package com.ticketbox.ui.screens

import com.ticketbox.domain.model.Expense
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.util.Locale

data class LedgerExpenseGroup(
    val key: String,
    val label: String,
    val items: List<Expense>,
)

fun groupLedgerExpenses(items: List<Expense>): List<LedgerExpenseGroup> {
    return items
        .groupBy { expense ->
            val date = expenseLedgerDate(expense)
            date?.toString() ?: "unknown"
        }
        .map { (key, expenses) ->
            val date = expenses.firstOrNull()?.let(::expenseLedgerDate)
            LedgerExpenseGroup(
                key = key,
                label = ledgerDayLabel(date),
                items = expenses,
            )
        }
}

fun expenseLedgerDate(expense: Expense): LocalDate? {
    val value = expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt
    return value.toLocalDateOrNull()
}

private fun String?.toLocalDateOrNull(): LocalDate? {
    if (this.isNullOrBlank()) return null
    val zone = ZoneId.systemDefault()
    return runCatching { Instant.parse(this).atZone(zone).toLocalDate() }
        .recoverCatching { OffsetDateTime.parse(this).toInstant().atZone(zone).toLocalDate() }
        .getOrNull()
}

fun ledgerDayLabel(date: LocalDate?): String {
    if (date == null) return "未设置日期"
    val today = LocalDate.now()
    return when (date) {
        today -> "今天"
        today.minusDays(1) -> "昨天"
        else -> date.format(DateTimeFormatter.ofPattern("M月d日 E", Locale.CHINA))
    }
}
