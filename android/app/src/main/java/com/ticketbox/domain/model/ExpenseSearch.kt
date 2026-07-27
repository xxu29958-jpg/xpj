package com.ticketbox.domain.model

import java.math.BigDecimal
import java.text.DecimalFormatSymbols
import java.time.ZoneId
import java.util.Locale

// Global-search query domain: amount parsing, amount matching, filter-chip
// facets and recent-search folding. Split from ExpenseFilters.kt to keep both
// files inside the detekt functions-per-file budget.

/** 全角符号别名：从各渠道复制的金额文本可能带全角 ￥/＄，与半角同义归一化。 */
private val FULLWIDTH_SYMBOL_ALIASES = mapOf('¥' to '￥', '$' to '＄')

/** 剥掉 [currency] 自己的币种符号（含全角别名，前/后缀皆可）与全部空白。 */
private fun stripSearchAmountContext(query: String, currency: CurrencyCode): String {
    var text = query.trim().replace(currency.symbol, "")
    FULLWIDTH_SYMBOL_ALIASES[currency.symbol.singleOrNull()]?.let { alias ->
        text = text.replace(alias.toString(), "")
    }
    return text.filterNot(Char::isWhitespace)
}

/**
 * 按 [currency] 的 locale 规则把已剥符号的金额文本归一化为 BigDecimal 可读的
 * ``digits[.fraction]`` 形态（PR#255 P2-1）：小数符/分组符取自该币种 `localeTag`
 * 的 [DecimalFormatSymbols]，与显示侧 formatAmount 同源 —— 因此 ``€1.234,50``
 * （de-DE：点分组、逗号小数）、``HK$1,234.50``、``₩1,200`` 这类从 Android 自己的
 * 格式化器复制出来的值都能解析，EUR 无符号的 ``12,50`` 也不会被误读成 1,250。
 *
 * 分隔符判定：两种都出现时靠右的是小数符；只出现分组符时，仅当整体是合法分组
 * 形态（``1.234`` / ``1,234,567``）才按分组剥离，否则按小数符对待 —— de-DE
 * 用户手输点号小数 ``12.50`` 不会被当分组放大成 1250。返回 null = 不是干净金额。
 */
private fun normalizeSearchAmountDigits(query: String, currency: CurrencyCode): String? {
    val stripped = stripSearchAmountContext(query, currency)
    if (stripped.isEmpty()) return null
    val symbols = DecimalFormatSymbols.getInstance(Locale.forLanguageTag(currency.localeTag))
    val decimal = symbols.decimalSeparator
    val grouping = symbols.groupingSeparator
    val hasDecimal = stripped.indexOf(decimal) >= 0
    val hasGrouping = decimal != grouping && stripped.indexOf(grouping) >= 0

    var text = stripped
    val decimalChar: Char? = when {
        hasDecimal && hasGrouping -> {
            // 两种分隔符都在：靠右的是小数符，另一种整组剥掉。
            val resolved = if (stripped.lastIndexOf(decimal) > stripped.lastIndexOf(grouping)) decimal else grouping
            val groupingChar = if (resolved == decimal) grouping else decimal
            text = text.replace(groupingChar.toString(), "")
            resolved
        }
        hasGrouping -> {
            val groupingPattern = Regex("^\\d{1,3}(\\Q$grouping\\E\\d{3})+$")
            if (groupingPattern.matches(text)) {
                text = text.replace(grouping.toString(), "")
                null
            } else {
                grouping
            }
        }
        hasDecimal -> decimal
        else -> null
    }
    if (decimalChar != null) {
        if (text.count { it == decimalChar } != 1) return null
        text = text.replace(decimalChar, '.')
    }
    return text.takeIf { it.matches(Regex("^\\d+(\\.\\d+)?$")) }
}

/**
 * Parse a global-search query into an exact minor-unit amount value, or null when
 * the query is not a clean money amount. Money discipline: major → minor via
 * [BigDecimal] (never float), scaled by [currency]'s minor-unit digits — a JPY-home
 * user typing "1200" means ¥1200 (minor 1200), not 120000.
 *
 * [currency] selects both the minor-unit scale and the display conventions that
 * are normalized away first: its own symbol (half/full-width, prefix or suffix)
 * and its locale's grouping/decimal separators (see [normalizeSearchAmountDigits]).
 * Other currencies' symbols are deliberately NOT stripped, so a formatted value
 * can only parse on its own currency's leg ("HK$1,234.50" never hits a USD leg).
 *
 * A query qualifies only when the normalized residue is a non-negative decimal
 * with **at most [CurrencyCode.minorUnitDigits]** fractional digits ("12", "12.5",
 * "¥12.50", "128" for a 2-digit currency; integers only for JPY/KRW). More
 * fraction digits ("12.345", or any fraction under a zero-decimal currency) or
 * any non-numeric residue yields null so the term falls back to pure text
 * matching rather than silently rounding to a minor value the user never typed.
 */
fun parseSearchAmountCents(
    query: String,
    currency: CurrencyCode = FxContract.HomeCurrency,
): Long? {
    val normalized = normalizeSearchAmountDigits(query, currency) ?: return null
    val fractionDigits = normalized.substringAfter('.', "").length
    if (fractionDigits > currency.minorUnitDigits) return null
    return runCatching {
        val decimal = BigDecimal(normalized)
        if (decimal.signum() < 0) return null
        decimal.movePointRight(currency.minorUnitDigits).longValueExact()
    }.getOrNull()
}

/**
 * 把 [query] 按**每个支持的币种各解析一次**并缓存成表（PR#255 P2-2）：逐行匹配
 * （[expenseMatchesSearchAmount] 的 map 重载）按行腿币种查表复用结果，避免在大
 * 账本缓存上每行重复构造 BigDecimal —— 非数字 query（"coffee"）短路为空表，
 * 金额腿直接判无命中，而不是每行抛一次解析异常。
 */
fun parseSearchAmountsByCurrency(query: String): Map<CurrencyCode, Long> {
    val trimmed = query.trim()
    if (trimmed.none(Char::isDigit)) return emptyMap()
    return CurrencyCode.entries.mapNotNull { currency ->
        parseSearchAmountCents(trimmed, currency)?.let { currency to it }
    }.toMap()
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
 * Per-row dual-leg amount matching (PR#255 P2): each leg is compared against the
 * pre-parsed amount **of its own currency** (see [parseSearchAmountsByCurrency]),
 * so cross-exponent rows are reachable from both directions —
 *
 * - home legs (`amountCents` / `homeAmountCents`) look up the row's
 *   `homeCurrency` parse; the original leg joins them only when the row has no
 *   foreign currency (same-currency legacy rows, where one parse serves all legs);
 * - a foreign original leg (`originalCurrencyCode` != home) instead looks up the
 *   parse of that original currency — never the home parse, so "1250" can't
 *   coincidentally hit a 12.50-USD minor.
 *
 * A JPY-home user searching "12.50" therefore still hits a USD-original row
 * (12.50 USD → 1250) even though the query isn't a valid zero-decimal home
 * amount, and a CNY-home user searching "1200" hits a JPY-original row
 * (1200 ≠ 120000 cents). Returns false when the query parsed on neither leg.
 */
fun expenseMatchesSearchAmount(expense: Expense, amountsByCurrency: Map<CurrencyCode, Long>): Boolean {
    if (amountsByCurrency.isEmpty()) return false
    val originalCurrency = expense.originalCurrencyCode
    val foreignOriginal = originalCurrency != expense.homeCurrency
    amountsByCurrency[expense.homeCurrency]?.let { homeAmount ->
        if (expense.amountCents == homeAmount || expense.homeAmountCents == homeAmount) return true
        if (!foreignOriginal && expense.originalAmountMinor == homeAmount) return true
    }
    if (foreignOriginal) {
        amountsByCurrency[originalCurrency]?.let { originalAmount ->
            if (expense.originalAmountMinor == originalAmount) return true
        }
    }
    return false
}

/** Convenience overload for single-shot callers/tests: parses [query] per
 *  supported currency once, then runs the cached-map match above. Hot paths
 *  (global search) must pre-parse via [parseSearchAmountsByCurrency] instead. */
fun expenseMatchesSearchAmount(expense: Expense, query: String): Boolean =
    expenseMatchesSearchAmount(expense, parseSearchAmountsByCurrency(query))

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
