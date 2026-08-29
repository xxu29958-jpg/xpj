package com.ticketbox.viewmodel

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.normalizeExpenseCategory
import com.ticketbox.ui.components.parseMinorAmount
import java.time.Instant
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import kotlin.math.abs

/** Scalar diff result; null fields mean the submitted correction left them unchanged. */
internal data class ScalarCorrectionChanges(
    val originalCurrencyCode: CurrencyCode? = null,
    val originalAmountMinor: Long? = null,
    val merchant: String? = null,
    val category: String? = null,
    val note: String? = null,
    val tags: String? = null,
    val expenseTime: String? = null,
    val expenseTimeChanged: Boolean = false,
    val valueScore: Int? = null,
    val valueScoreChanged: Boolean = false,
    val regretScore: Int? = null,
    val regretScoreChanged: Boolean = false,
) {
    val hasAny: Boolean
        get() = originalAmountMinor != null || merchant != null || category != null ||
            note != null || tags != null || expenseTimeChanged ||
            valueScoreChanged || regretScoreChanged
}

internal class CorrectionValidationError(@param:StringRes val resId: Int) : Exception()

private val LOCAL_TIME_FORMATS = listOf(
    DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm"),
    DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm"),
)
private val CORRECTION_TIME_DISPLAY = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm")

private fun parseCorrectionTimeIso(text: String, zoneId: ZoneId): String {
    val cleaned = text.trim()
    for (format in LOCAL_TIME_FORMATS) {
        try {
            val local = LocalDateTime.parse(cleaned, format)
            return local.atZone(zoneId).toInstant().toString()
        } catch (_: java.time.format.DateTimeParseException) {
            // try next format
        }
    }
    throw CorrectionValidationError(R.string.expense_correction_time_invalid)
}

private fun formatCorrectionTimeInput(value: String?, zoneId: ZoneId): String {
    if (value.isNullOrBlank()) return ""
    val instant = runCatching { Instant.parse(value) }
        .recoverCatching { OffsetDateTime.parse(value).toInstant() }
        .getOrNull() ?: return ""
    return instant.atZone(zoneId).format(CORRECTION_TIME_DISPLAY)
}

private fun sameInstant(first: String?, second: String?): Boolean {
    if (first == null || second == null) return first == second
    val firstInstant = runCatching { Instant.parse(first) }
        .recoverCatching { OffsetDateTime.parse(first).toInstant() }
        .getOrNull()
    val secondInstant = runCatching { Instant.parse(second) }
        .recoverCatching { OffsetDateTime.parse(second).toInstant() }
        .getOrNull()
    return firstInstant != null && firstInstant == secondInstant
}

private fun Expense.originalCurrencyRaw(): String =
    originalCurrencyCodeRaw?.trim()?.uppercase()?.takeIf { it.isNotBlank() }
        ?: originalCurrencyCode.storageKey

private fun Expense.originalCurrencyOrNull(): CurrencyCode? =
    CurrencyCode.fromStorageKeyOrNull(originalCurrencyRaw())

private fun initialCorrectionAmountText(expense: Expense): String {
    val minor = expense.originalAmountMinor ?: expense.amountCents ?: return ""
    val currency = expense.originalCurrencyOrNull()
    return if (currency == null) {
        abs(minor).toString()
    } else {
        com.ticketbox.ui.components.formatMinorAmountInput(abs(minor), currency)
    }
}

private fun computeAmountChanges(
    expense: Expense,
    form: CorrectionFormState,
): Pair<CurrencyCode?, Long?> {
    if (form.amountText.isBlank()) return null to null
    val baselineMinor = expense.originalAmountMinor ?: expense.amountCents
    val baselineCurrency = expense.originalCurrencyOrNull()
    if (baselineCurrency == null && !form.currencyTouched) {
        if (form.amountText.trim() == baselineMinor?.let { abs(it).toString() }.orEmpty()) {
            return null to null
        }
        throw CorrectionValidationError(R.string.expense_correction_currency_unsupported)
    }
    val targetCurrency = if (form.currencyTouched) form.currency else requireNotNull(baselineCurrency)
    val targetMinor = parseMinorAmount(form.amountText, targetCurrency)
        ?: throw CorrectionValidationError(R.string.expense_correction_amount_invalid)
    val currencyChanged = targetCurrency.storageKey != expense.originalCurrencyRaw()
    return if (targetMinor != baselineMinor || currencyChanged) {
        targetCurrency to targetMinor
    } else {
        null to null
    }
}

internal fun computeScalarChanges(
    expense: Expense,
    form: CorrectionFormState,
    zoneId: ZoneId,
): ScalarCorrectionChanges {
    val (originalCurrencyCode, originalAmountMinor) = computeAmountChanges(expense, form)
    val merchant = form.merchant.trim().takeIf { it != expense.merchant.orEmpty() }
    val categoryInput = form.category.trim()
    val category = categoryInput.takeIf {
        it.isNotEmpty() && normalizeExpenseCategory(it) != normalizeExpenseCategory(expense.category)
    }?.let { normalizeExpenseCategory(it) }
    val note = form.note.takeIf { it != expense.note.orEmpty() }
    val tags = form.tags.trim().takeIf { it != expense.tags.orEmpty() }
    val expenseTimeChanged: Boolean
    val expenseTime: String?
    if (form.expenseTimeText.isBlank()) {
        expenseTimeChanged = expense.expenseTime != null
        expenseTime = null
    } else {
        val parsed = parseCorrectionTimeIso(form.expenseTimeText, zoneId)
        expenseTimeChanged = !sameInstant(parsed, expense.expenseTime)
        expenseTime = parsed.takeIf { expenseTimeChanged }
    }
    if (form.valueScore !in listOf(null, 1, 2, 3, 4, 5) ||
        form.regretScore !in listOf(null, 1, 2, 3, 4, 5)
    ) {
        throw CorrectionValidationError(R.string.expense_correction_score_invalid)
    }
    val valueScoreChanged = form.valueScore != expense.valueScore
    val regretScoreChanged = form.regretScore != expense.regretScore
    return ScalarCorrectionChanges(
        originalCurrencyCode = originalCurrencyCode,
        originalAmountMinor = originalAmountMinor,
        merchant = merchant,
        category = category,
        note = note,
        tags = tags,
        expenseTime = expenseTime,
        expenseTimeChanged = expenseTimeChanged,
        valueScore = form.valueScore.takeIf { valueScoreChanged },
        valueScoreChanged = valueScoreChanged,
        regretScore = form.regretScore.takeIf { regretScoreChanged },
        regretScoreChanged = regretScoreChanged,
    )
}

internal fun initialCorrectionFormState(expense: Expense, zoneId: ZoneId): CorrectionFormState {
    val rawCurrency = expense.originalCurrencyRaw()
    val knownCurrency = expense.originalCurrencyOrNull()
    val homeRaw = expense.homeCurrencyCode?.trim()?.uppercase()?.takeIf { it.isNotBlank() }
        ?: expense.homeCurrency.storageKey
    return CorrectionFormState(
        open = true,
        merchant = expense.merchant.orEmpty(),
        category = expense.category,
        tags = expense.tags.orEmpty(),
        note = expense.note.orEmpty(),
        amountText = initialCorrectionAmountText(expense),
        currency = knownCurrency ?: expense.originalCurrencyCode,
        unsupportedCurrencyCode = rawCurrency.takeIf { knownCurrency == null },
        foreignCurrency = rawCurrency != homeRaw,
        expenseTimeText = formatCorrectionTimeInput(expense.expenseTime, zoneId),
        valueScore = expense.valueScore,
        regretScore = expense.regretScore,
    )
}
