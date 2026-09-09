package com.ticketbox.domain.model

import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.YearMonth
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

private val TAG_SPLIT_REGEX = Regex("[,，;；\\n]+")

data class ExpenseFilterCriteria(
    val month: String = "",
    val category: String = "",
    val tag: String = "",
    val query: String = "",
    val zoneId: ZoneId = ZoneId.systemDefault(),
)

fun filterConfirmedExpenses(
    expenses: List<Expense>,
    criteria: ExpenseFilterCriteria = ExpenseFilterCriteria(),
): List<Expense> {
    val cleanMonth = criteria.month.trim()
    val cleanCategory = criteria.category.trim()
    val cleanTag = criteria.tag.trim()
    val cleanTagKey = cleanTag.lowercase()
    val cleanQuery = criteria.query.trim().lowercase()
    val targetMonth = cleanMonth
        .takeIf { it.isNotBlank() }
        ?.let { value -> runCatching { YearMonth.parse(value) }.getOrNull() }
    if (cleanMonth.isNotBlank() && targetMonth == null) {
        return emptyList()
    }
    return expenses.filter { expense ->
        val expenseMonth = expense.ledgerLocalDate(criteria.zoneId)?.let { YearMonth.from(it) }
        val monthMatched = targetMonth == null || expenseMonth == targetMonth
        val categoryMatched = cleanCategory.isBlank() || expense.category == cleanCategory
        val tagMatched = cleanTag.isBlank() || expense.normalizedTagNames().any { it.lowercase() == cleanTagKey }
        val queryMatched = cleanQuery.isBlank() || listOfNotNull(
            expense.merchant,
            expense.category,
            expense.note,
            expense.tags,
            expense.source,
        ).any { it.lowercase().contains(cleanQuery) }
        monthMatched && categoryMatched && tagMatched && queryMatched
    }
}

fun expenseLedgerMonth(
    expense: Expense,
    zoneId: ZoneId = ZoneId.systemDefault(),
): String? {
    return expense.ledgerLocalDate(zoneId)?.let { YearMonth.from(it).toString() }
}

/**
 * The most-recently-used merchants from the confirmed cache, each carrying the
 * category last paired with it — fuel for the manual-entry sheet's "最近" quick
 * fill. Ordered newest-first by the expense's own timestamp (ISO-8601 strings
 * sort in time order), de-duplicated by merchant so the first (most recent)
 * occurrence wins both the slot and its category. Blank merchants are skipped.
 *
 * This is a pure derivation over already-confirmed rows the user created or
 * approved — tapping a chip is a manual fill, so it does not run afoul of the
 * "AI/OCR only fills blanks" rule.
 */
fun recentLedgerMerchants(
    expenses: List<Expense>,
    limit: Int = 8,
): List<RecentMerchant> {
    if (limit <= 0) return emptyList()
    val seen = mutableSetOf<String>()
    return expenses
        .asSequence()
        .sortedByDescending { it.expenseTime ?: it.confirmedAt ?: it.createdAt }
        .mapNotNull { expense ->
            val merchant = expense.merchant?.trim()?.takeIf { it.isNotBlank() } ?: return@mapNotNull null
            if (!seen.add(merchant.lowercase())) return@mapNotNull null
            RecentMerchant(merchant = merchant, category = expense.category)
        }
        .take(limit)
        .toList()
}

/**
 * Step a ``yyyy-MM`` ledger month by [delta] months, returning the new
 * ``yyyy-MM`` string. Blank or unparseable input (e.g. the "全部月份" sentinel)
 * yields null so the caller can hide the prev/next affordance rather than
 * inventing a month. Pure — drives the ledger inline ‹ › month switch.
 */
fun shiftLedgerMonth(month: String, delta: Long): String? {
    val parsed = runCatching { YearMonth.parse(month.trim()) }.getOrNull() ?: return null
    return parsed.plusMonths(delta).toString()
}

internal fun Expense.normalizedTagNames(): List<String> {
    val raw = tags ?: return emptyList()
    val seen = mutableSetOf<String>()
    return TAG_SPLIT_REGEX.split(raw)
        .map { it.trim().replace(Regex("\\s+"), " ") }
        .filter { it.isNotBlank() }
        .filter { seen.add(it.lowercase()) }
}

private fun Expense.ledgerLocalDate(zoneId: ZoneId): LocalDate? {
    val value = expenseTime ?: confirmedAt ?: createdAt
    return runCatching { Instant.parse(value).atZone(zoneId).toLocalDate() }
        .recoverCatching { OffsetDateTime.parse(value).toInstant().atZone(zoneId).toLocalDate() }
        .recoverCatching { LocalDate.parse(value.take(10)) }
        .getOrNull()
}
