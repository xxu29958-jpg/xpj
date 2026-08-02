package com.ticketbox.domain.model

// Global-search amount-query parsing (PR#255 R14-4): the per-currency parse cache
// plus the explicit trailing-code path ("1200 VND" paste). Split from
// ExpenseSearch.kt to keep both files inside the detekt functions-per-file budget.

/**
 * 一次搜索查询的金额解析结果（PR#255 R14-4b）。
 *
 * 无显式币种码时 [amountsByCurrency] 按每个支持币种各解析一次（见
 * [expenseMatchesSearchAmount] 的 map 重载注释）；查询带**尾部显式三字母码**
 * （"1200 VND" / "12.50 USD"，空白分隔）时改走严格单码口径：[explicitCode] 为剥离出的
 * 大写码（支持集内外皆可），[explicitMinor] 为按该码解析的 minor 值 —— 已知码按其
 * exponent 缩放，未知码按原 minor 整数（JPY 零小数代理解析：不缩放、拒小数，与 R10⑥
 * home 侧同源）。显式码路径下 [amountsByCurrency] 恒为空：不做跨币种猜测（"12.50 USD"
 * 不得巧合命中 ¥12.50 的 CNY 腿）。
 */
data class ParsedSearchAmounts(
    val amountsByCurrency: Map<CurrencyCode, Long>,
    val explicitCode: String? = null,
    val explicitMinor: Long? = null,
)

/** 尾部显式三字母币种码：金额部分与码之间至少一个空白（"1200 VND"、"12.50 usd"）。 */
private val EXPLICIT_SEARCH_CODE_REGEX = Regex("^(.*\\S)\\s+([A-Za-z]{3})$")

/**
 * 把 [query] 解析成金额匹配燃料（PR#255 P2-2 / R14-4b）。非数字 query（"coffee"）短路
 * 为空结果，金额腿直接判无命中，而不是每行抛一次解析异常。尾部显式码先剥离再按该码
 * 严格解析（未知码按原 minor）；否则按**每个支持的币种各解析一次**缓存成表，逐行匹配
 * 按行腿币种查表复用，避免在大账本缓存上每行重复构造 BigDecimal。
 */
fun parseSearchAmountsByCurrency(query: String): ParsedSearchAmounts {
    val trimmed = query.trim()
    if (trimmed.none(Char::isDigit)) return ParsedSearchAmounts(emptyMap())
    val explicit = EXPLICIT_SEARCH_CODE_REGEX.matchEntire(trimmed)
    if (explicit != null) {
        val amountPart = explicit.groupValues[1]
        val code = explicit.groupValues[2].uppercase()
        val known = CurrencyCode.fromStorageKeyOrNull(code)
        // 未知码按原 minor 整数解析（JPY 代理 = 不缩放且拒非零小数）；已知码按其币种规则。
        val minor = parseSearchAmountCents(amountPart, known ?: CurrencyCode.JPY)
        return ParsedSearchAmounts(
            amountsByCurrency = emptyMap(),
            explicitCode = code,
            explicitMinor = minor,
        )
    }
    return ParsedSearchAmounts(
        amountsByCurrency = CurrencyCode.entries.mapNotNull { currency ->
            parseSearchAmountCents(trimmed, currency)?.let { currency to it }
        }.toMap(),
    )
}

/**
 * 显式码感知的逐行匹配（R14-4）：显式码查询走严格单码（只比 raw 码等于查询码的腿 ——
 * home 双腿 + original 腿，未知码行亦按原码原 minor 命中，"1200 VND" 粘贴直查可达）；
 * 否则委托每币种缓存表的双腿匹配。
 */
fun expenseMatchesSearchAmount(expense: Expense, parsed: ParsedSearchAmounts): Boolean {
    val explicitCode = parsed.explicitCode ?: return expenseMatchesSearchAmount(expense, parsed.amountsByCurrency)
    val minor = parsed.explicitMinor ?: return false
    if (expenseHomeCodeKey(expense) == explicitCode &&
        (expense.amountCents == minor || expense.homeAmountCents == minor)
    ) {
        return true
    }
    return expenseOriginalCodeKey(expense) == explicitCode && expense.originalAmountMinor == minor
}

/**
 * Per-row dual-leg amount matching (PR#255 P2): each leg is compared against the
 * pre-parsed amount **of its own currency** (see [parseSearchAmountsByCurrency]),
 * so cross-exponent rows are reachable from both directions —
 *
 * - home legs (`amountCents` / `homeAmountCents`) look up the row's
 *   `homeCurrency` parse; the original leg joins them only when the row has no
 *   foreign currency (same-currency legacy rows, where one parse serves all legs);
 * - a foreign original leg (original code != home — 判定为 R14-4a 原码感知，见
 *   [isForeignOriginal]) instead looks up the parse of that original currency —
 *   never the home parse, so "1250" can't coincidentally hit a 12.50-USD minor.
 *
 * A JPY-home user searching "12.50" therefore still hits a USD-original row
 * (12.50 USD → 1250) even though the query isn't a valid zero-decimal home
 * amount, and a CNY-home user searching "1200" hits a JPY-original row
 * (1200 ≠ 120000 cents). Returns false when the query parsed on neither leg.
 */
fun expenseMatchesSearchAmount(expense: Expense, amountsByCurrency: Map<CurrencyCode, Long>): Boolean {
    if (amountsByCurrency.isEmpty()) return false
    // PR#255 R10⑥：home 码**非空但**在支持集外（新版服务端币种）时，金额匹配按原 minor
    // 整数值（与 R8-4 显示口径 "1200 VND" 一致，显示多少搜得到多少）——零小数解析恰好
    // 是未缩放整数（"1200"→1200；小数查询天然不命中，minor 必为整数），用它作原值代理。
    // raw 为空/缺省（旧 record / 手工构造）不落此分支，维持枚举口径（行为不回归）。
    val rawHomeCode = expense.homeCurrencyCode
    val homeUnknown = !rawHomeCode.isNullOrBlank() && CurrencyCode.fromStorageKeyOrNull(rawHomeCode) == null
    if (homeUnknown && matchUnknownHomeRawLeg(expense, amountsByCurrency)) return true
    if (!homeUnknown && matchesKnownHomeLegs(expense, amountsByCurrency)) return true
    return matchesForeignOriginalLeg(expense, amountsByCurrency)
}

/** 已知 home 行的双腿匹配：home 解析命中 home 双腿；本币行（无外币腿）original 腿同参续配。 */
private fun matchesKnownHomeLegs(expense: Expense, amountsByCurrency: Map<CurrencyCode, Long>): Boolean {
    val homeAmount = amountsByCurrency[expense.homeCurrency] ?: return false
    if (expense.amountCents == homeAmount || expense.homeAmountCents == homeAmount) return true
    return !isForeignOriginal(expense) && expense.originalAmountMinor == homeAmount
}

/** R12-B：未知 home 行的 raw-minor 匹配只比 home 双腿（amountCents/homeAmountCents）——
 *  original 腿交回 [matchesForeignOriginalLeg] 按其声明币种续配（VND-home/USD-original 双路可达）。 */
private fun matchUnknownHomeRawLeg(expense: Expense, amountsByCurrency: Map<CurrencyCode, Long>): Boolean {
    val raw = amountsByCurrency[CurrencyCode.JPY] ?: return false
    return expense.amountCents == raw || expense.homeAmountCents == raw
}

/**
 * R14-4a：foreignOriginal 判定改原码感知 —— 原码（R13-4 raw）非空时按码键比较：
 * 未知原码的枚举已回落 CNY，枚举相等判定会把 VND-original/CNY-home 行当成本币行，
 * 让 "12.00" 的 home 解析（1200 分）巧合命中 1200-VND 原 minor。原码缺失维持枚举判定。
 */
private fun isForeignOriginal(expense: Expense): Boolean {
    val originalCodeKey = expenseOriginalRawCodeKeyOrNull(expense)
    return when {
        originalCodeKey != null -> originalCodeKey != expenseHomeCodeKey(expense)
        else -> expense.originalCurrencyCode != expense.homeCurrency
    }
}

/** 外币 original 腿匹配：未知原码按原 minor 整数值比（JPY 代理，同 R10⑥ home 侧口径，
 *  不按回落枚举的声明码续配）；已知码按声明币种续配。 */
private fun matchesForeignOriginalLeg(expense: Expense, amountsByCurrency: Map<CurrencyCode, Long>): Boolean {
    if (!isForeignOriginal(expense)) return false
    val originalAmount = expense.originalAmountMinor ?: return false
    val originalCodeKey = expenseOriginalRawCodeKeyOrNull(expense)
    if (originalCodeKey != null && CurrencyCode.fromStorageKeyOrNull(originalCodeKey) == null) {
        return amountsByCurrency[CurrencyCode.JPY] == originalAmount
    }
    val declared = CurrencyCode.fromStorageKeyOrNull(originalCodeKey) ?: expense.originalCurrencyCode
    return amountsByCurrency[declared] == originalAmount
}

/** 行 original 腿的 raw 码键（R13-4 原码优先，未知码不被枚举回落掩盖；缺失回落枚举键）。 */
internal fun expenseOriginalCodeKey(expense: Expense): String =
    expenseOriginalRawCodeKeyOrNull(expense) ?: expense.originalCurrencyCode.storageKey

/** 原码键的可空形态（blank 视为缺失）：匹配分支内部用。 */
private fun expenseOriginalRawCodeKeyOrNull(expense: Expense): String? =
    expense.originalCurrencyCodeRaw?.trim()?.uppercase()?.takeIf { it.isNotBlank() }

/** 行 home 腿的 raw 码键（大写；raw 缺/空回落枚举键 —— 手工构造与旧 record 的既有口径）。 */
internal fun expenseHomeCodeKey(expense: Expense): String =
    expense.homeCurrencyCode?.trim()?.uppercase()?.takeIf { it.isNotBlank() }
        ?: expense.homeCurrency.storageKey
