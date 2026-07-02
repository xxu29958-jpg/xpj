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
) {
    /**
     * Sum of this day's confirmed amounts in home-currency minor units (rows
     * with a null amount contribute 0). Rendered as the day-header subtotal so
     * the list reads as daily totals, not just a flat stream. Pure derivation —
     * unit-tested through [groupLedgerExpenses].
     */
    val dayTotalCents: Long get() = items.sumOf { it.amountCents ?: 0L }
    val itemCount: Int get() = items.size
}

internal fun ledgerDayPreviewLabels(items: List<Expense>, limit: Int): List<String> {
    return items
        .mapNotNull { expense -> expense.previewLabel()?.let { LedgerDayPreviewCandidate(it, expense.amountCents ?: 0L) } }
        .groupBy { it.label }
        .map { (label, candidates) -> LedgerDayPreviewCandidate(label, candidates.maxOf { it.amountCents }) }
        .sortedWith(compareByDescending<LedgerDayPreviewCandidate> { it.amountCents }.thenBy { it.label })
        .take(limit)
        .map { it.label }
}

fun groupLedgerExpenses(resources: Resources, items: List<Expense>): List<LedgerExpenseGroup> {
    return items
        .sortedWith(compareByDescending<Expense> { expenseLedgerDate(it) ?: LocalDate.MIN }.thenByDescending { ledgerSortTime(it) })
        .groupBy { expense ->
            expenseLedgerDate(expense)?.toString() ?: UNKNOWN_LEDGER_DAY_KEY
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

private fun ledgerSortTime(expense: Expense): String = expense.expenseTime ?: expense.confirmedAt ?: expense.createdAt

private fun Expense.previewLabel(): String? {
    return merchant?.trim()?.takeIf { it.isNotBlank() }
        ?: category.trim().takeIf { it.isNotBlank() }
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

private data class LedgerDayPreviewCandidate(
    val label: String,
    val amountCents: Long,
)

private const val UNKNOWN_LEDGER_DAY_KEY = "unknown"
