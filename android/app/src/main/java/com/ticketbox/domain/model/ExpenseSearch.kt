package com.ticketbox.domain.model

import java.math.BigDecimal
import java.time.ZoneId

// Global-search query domain: amount parsing, amount matching, filter-chip
// facets and recent-search folding. Split from ExpenseFilters.kt to keep both
// files inside the detekt functions-per-file budget.

private val EXPLICIT_CURRENCY_AMOUNT_REGEX = Regex("""^([A-Za-z]{3})\s+(.+)$""")
private val SEARCH_MAJOR_AMOUNT_REGEX =
    Regex("""^(?:\d+|\d{1,3}(?:[,，]\d{3})+)(?:\.(\d+))?$""")

/**
 * An exact amount-search term. Currency is always explicit in the parsed
 * result: either the caller's server-authoritative home currency, or an ISO
 * code typed by the user.
 */
data class SearchMoneyAmount(
    val currency: CurrencyCode,
    val amountMinor: Long,
)

/**
 * Parse a global-search query into an exact currency + minor-unit value.
 *
 * A bare numeric term uses [homeCurrency]. A foreign amount must use the
 * unambiguous `USD 12.50` / `JPY 1200` syntax. Symbols and locale are never
 * used to guess currency because `¥` is shared by CNY and JPY. Fraction digits
 * are checked against the selected currency before [BigDecimal] performs an
 * exact, no-rounding conversion.
 */
fun parseSearchMoneyAmount(
    query: String,
    homeCurrency: CurrencyCode,
): SearchMoneyAmount? {
    val term = query.trim()
    if (term.isBlank()) return null
    val explicit = EXPLICIT_CURRENCY_AMOUNT_REGEX.matchEntire(term)
    val currency = if (explicit == null) {
        homeCurrency
    } else {
        runCatching { CurrencyCode.requireSupported(explicit.groupValues[1]) }.getOrNull()
            ?: return null
    }
    val amountText = explicit?.groupValues?.get(2) ?: term
    val amountMatch = SEARCH_MAJOR_AMOUNT_REGEX.matchEntire(amountText) ?: return null
    val fractionDigits = amountMatch.groupValues[1].length
    if (fractionDigits > currency.minorUnitDigits) return null
    val normalized = amountText.replace(",", "").replace("，", "")
    val amountMinor = runCatching {
        BigDecimal(normalized)
            .movePointRight(currency.minorUnitDigits)
            .longValueExact()
    }.getOrNull() ?: return null
    return SearchMoneyAmount(currency = currency, amountMinor = amountMinor)
}

/**
 * Match only a leg carrying the query's explicit currency. This prevents the
 * same integer minor value from being treated as interchangeable across CNY,
 * JPY, USD, and other currencies.
 */
fun expenseMatchesSearchAmount(expense: Expense, amount: SearchMoneyAmount): Boolean {
    val homeMatches =
        expense.homeCurrency == amount.currency &&
            (expense.homeAmountCents ?: expense.amountCents) == amount.amountMinor
    val originalMatches =
        expense.originalCurrencyCode == amount.currency &&
            expense.originalAmountMinor == amount.amountMinor
    return homeMatches || originalMatches
}

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
