package com.ticketbox.domain.model

import java.math.BigDecimal
import java.time.ZoneId

// Global-search query domain: amount parsing, amount matching, filter-chip
// facets and recent-search folding. Split from ExpenseFilters.kt to keep both
// files inside the detekt functions-per-file budget.

/** Currency symbols / grouping marks a user may type before an amount in the
 *  global-search box ("¥12.50", "￥12", "1,280"). Stripped before parsing. */
private val SEARCH_AMOUNT_NOISE_REGEX = Regex("[¥￥$＄,，\\s]")

/**
 * Parse a global-search query into an exact `amount_cents` value, or null when
 * the query is not a clean money amount. Money discipline: yuan → cents via
 * [BigDecimal] (never float), reusing the project's "× 100 in one place" rule.
 *
 * A query qualifies only when, after stripping a leading currency symbol /
 * grouping marks, what remains is a non-negative decimal with **at most two**
 * fractional digits ("12", "12.5", "¥12.50", "128"). More than two fraction
 * digits ("12.345") or any non-numeric residue yields null so the term falls
 * back to pure text matching rather than silently rounding to a cent value the
 * user never typed.
 */
fun parseSearchAmountCents(query: String): Long? {
    val cleaned = query.trim().replace(SEARCH_AMOUNT_NOISE_REGEX, "")
    if (cleaned.isBlank()) return null
    val fractionDigits = cleaned.substringAfter('.', "").length
    if (fractionDigits > 2) return null
    return runCatching {
        val decimal = BigDecimal(cleaned)
        if (decimal.signum() < 0) return null
        decimal.movePointRight(2).longValueExact()
    }.getOrNull()
}

/**
 * True when [expense] matches the parsed search amount on any currency leg —
 * the home/base `amount_cents` or the original foreign minor amount — so a
 * search for "12.50" finds a ¥12.50 row regardless of which leg the user
 * remembers. Pure cents-vs-cents integer compare.
 */
fun expenseMatchesAmountCents(expense: Expense, amountCents: Long): Boolean =
    expense.amountCents == amountCents ||
        expense.homeAmountCents == amountCents ||
        expense.originalAmountMinor == amountCents

/**
 * Distinct ``yyyy-MM`` ledger months present in [expenses], newest first —
 * fuel for the search month-filter chips and picker. Derived from the local
 * caches (same `expense_time → confirmed_at → created_at` fallback as the rest
 * of the ledger), so the chips only ever offer months that actually have rows.
 */
fun searchableMonths(
    expenses: List<Expense>,
    zoneId: ZoneId = ZoneId.systemDefault(),
): List<String> =
    expenses
        .mapNotNull { expenseLedgerMonth(it, zoneId) }
        .distinct()
        .sortedDescending()

/**
 * Categories offered by the search category-filter chips: the default catalog
 * first (stable, familiar order), then any extra categories that show up in the
 * local [expenses] caches, de-duplicated. Mirrors the ledger filter's category
 * source so the two surfaces agree.
 */
fun searchableCategories(expenses: List<Expense>): List<String> =
    mergeExpenseCategories(expenses.map { it.category })

/**
 * Fold a freshly committed [query] into the recent-search history: trimmed,
 * most-recent-first, case-insensitively de-duplicated (an existing entry moves
 * to the front rather than duplicating), capped at [max]. Blank queries are a
 * no-op (return the list unchanged). Pure — the VM persists the result.
 */
fun appendRecentSearch(
    existing: List<String>,
    query: String,
    max: Int = RECENT_SEARCH_LIMIT,
): List<String> {
    val trimmed = query.trim()
    if (trimmed.isBlank() || max <= 0) return existing.take(max.coerceAtLeast(0))
    val deduped = existing.filter { it.trim().lowercase() != trimmed.lowercase() }
    return (listOf(trimmed) + deduped).take(max)
}

/** Cap on how many recent search queries are remembered locally. */
const val RECENT_SEARCH_LIMIT = 8
