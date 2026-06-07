package com.ticketbox.ui.screens

import android.content.res.Resources
import com.ticketbox.R
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

fun groupLedgerExpenses(resources: Resources, items: List<Expense>): List<LedgerExpenseGroup> {
    return items
        .groupBy { expense ->
            val date = expenseLedgerDate(expense)
            date?.toString() ?: "unknown"
        }
        .map { (key, expenses) ->
            val date = expenses.firstOrNull()?.let(::expenseLedgerDate)
            LedgerExpenseGroup(
                key = key,
                label = ledgerDayLabel(resources, date),
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

fun ledgerDayLabel(resources: Resources, date: LocalDate?): String {
    if (date == null) return resources.getString(R.string.ledger_day_no_date)
    val today = LocalDate.now()
    return when (date) {
        today -> resources.getString(R.string.ledger_day_today)
        today.minusDays(1) -> resources.getString(R.string.ledger_day_yesterday)
        // Date format pattern (not UI copy): 月/日 are DateTimeFormatter literal
        // delimiters, left as-is to keep the formatted output byte-identical.
        else -> date.format(DateTimeFormatter.ofPattern("M月d日 E", Locale.CHINA))
    }
}
