package com.ticketbox.domain.model

import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.YearMonth
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.roundToInt

private val TAG_SPLIT_REGEX = Regex("[,，;；\\n]+")

fun filterConfirmedExpenses(
    expenses: List<Expense>,
    month: String,
    category: String,
    tag: String = "",
    query: String = "",
    zoneId: ZoneId = ZoneId.systemDefault(),
): List<Expense> {
    val cleanMonth = month.trim()
    val cleanCategory = category.trim()
    val cleanTag = tag.trim()
    val cleanTagKey = cleanTag.lowercase()
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

fun monthlyStatsFromConfirmedExpenses(
    expenses: List<Expense>,
    month: String,
    tag: String = "",
    zoneId: ZoneId = ZoneId.systemDefault(),
): MonthlyStats? {
    val targetMonth = runCatching { YearMonth.parse(month.trim()) }.getOrNull() ?: return null
    val matched = filterConfirmedExpenses(
        expenses = expenses,
        month = targetMonth.toString(),
        category = "",
        tag = tag,
        zoneId = zoneId,
    ).filter { it.amountCents != null }

    if (matched.isEmpty()) {
        return null
    }

    val byCategory = matched
        .groupBy { it.category }
        .map { (category, items) ->
            CategoryStats(
                category = category,
                amountCents = items.sumOf { it.amountCents ?: 0L },
                count = items.size,
            )
        }
        .filter { it.amountCents > 0L && it.count > 0 }
        .sortedByDescending { it.amountCents }
    val byTag = matched
        .flatMap { expense ->
            expense.normalizedTagNames().map { tag -> tag to expense }
        }
        .groupBy(keySelector = { it.first }, valueTransform = { it.second })
        .map { (tag, items) ->
            TagStats(
                tag = tag,
                amountCents = items.sumOf { it.amountCents ?: 0L },
                count = items.size,
            )
        }
        .filter { it.amountCents > 0L && it.count > 0 }
        .sortedByDescending { it.amountCents }

    val total = byCategory.sumOf { it.amountCents }
    val count = byCategory.sumOf { it.count }
    if (total <= 0L || count <= 0) {
        return null
    }

    return MonthlyStats(
        month = targetMonth.toString(),
        totalAmountCents = total,
        count = count,
        byCategory = byCategory,
        byTag = byTag,
    )
}

private fun Expense.normalizedTagNames(): List<String> {
    val raw = tags ?: return emptyList()
    val seen = mutableSetOf<String>()
    return TAG_SPLIT_REGEX.split(raw)
        .map { it.trim().replace(Regex("\\s+"), " ") }
        .filter { it.isNotBlank() }
        .filter { seen.add(it.lowercase()) }
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

fun monthlyCategoryInsight(stats: MonthlyStats?): CategoryInsight? {
    val monthlyStats = stats ?: return null
    if (monthlyStats.totalAmountCents <= 0L || monthlyStats.count <= 0) {
        return null
    }
    val categories = monthlyStats.byCategory
        .filter { it.amountCents > 0L && it.count > 0 }
        .sortedByDescending { it.amountCents }
    val top = categories.firstOrNull() ?: return null
    val topShare = ((top.amountCents.toDouble() / monthlyStats.totalAmountCents.toDouble()) * 100)
        .roundToInt()
        .coerceIn(0, 100)
    return CategoryInsight(
        topCategory = top.category,
        topAmountCents = top.amountCents,
        topSharePercent = topShare,
        averagePerExpenseCents = monthlyStats.totalAmountCents / monthlyStats.count.toLong(),
        categoryCount = categories.size,
        isConcentrated = topShare >= 60,
    )
}

private fun Expense.ledgerLocalDate(zoneId: ZoneId): LocalDate? {
    val value = expenseTime ?: confirmedAt ?: createdAt
    return runCatching { Instant.parse(value).atZone(zoneId).toLocalDate() }
        .recoverCatching { OffsetDateTime.parse(value).toInstant().atZone(zoneId).toLocalDate() }
        .recoverCatching { LocalDate.parse(value.take(10)) }
        .getOrNull()
}
