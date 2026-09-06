package com.ticketbox.viewmodel

import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseSplits
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.MONEY_MINOR_MAX
import java.math.BigDecimal
import java.math.RoundingMode

/** Local certainty gate for corrections that would otherwise queue a known-invalid split aggregate. */
internal fun wouldOverallocateLoadedSplits(
    expense: Expense,
    draft: ExpenseCorrectionDraft,
    currentSplits: ExpenseSplits?,
): Boolean {
    currentSplits ?: return false
    val projectedParent = projectedCorrectionParent(expense, draft) ?: return false
    val splitTotal = if (draft.splits == null) {
        currentSplits.splitsTotalAmountCents ?: 0L
    } else {
        draft.splits.fold(0L) { total, split ->
            runCatching { Math.addExact(total, split.amountCents) }.getOrNull() ?: return true
        }
    }
    return splitTotal > projectedParent
}

private fun projectedCorrectionParent(
    expense: Expense,
    draft: ExpenseCorrectionDraft,
): Long? {
    val changesMoney = draft.amountCents != null ||
        draft.originalCurrencyCode != null ||
        draft.originalAmountMinor != null
    if (!changesMoney) return expense.amountCents
    draft.amountCents?.let { return it }
    val targetCurrency = draft.originalCurrencyCode ?: return null
    val targetAmount = draft.originalAmountMinor ?: return null
    val homeCurrency = CurrencyCode.fromStorageKeyOrNull(expense.homeCurrencyCode)
        ?: expense.homeCurrency.takeIf { expense.homeCurrencyCode.isNullOrBlank() } ?: return null
    if (targetCurrency == homeCurrency) return targetAmount
    val originalCurrency = CurrencyCode.fromStorageKeyOrNull(expense.originalCurrencyCodeRaw)
        ?: expense.originalCurrencyCode.takeIf { expense.originalCurrencyCodeRaw.isNullOrBlank() }
    if (draft.expenseTimeChanged || targetCurrency != originalCurrency || expense.fxStatus != FxContract.StatusReady) return null
    val rate = expense.exchangeRateToCny?.trim()?.toBigDecimalOrNull()?.takeIf { it.signum() > 0 } ?: return null
    // Validation-only use of the existing frozen snapshot; never a canonical publication.
    return runCatching {
        BigDecimal.valueOf(targetAmount).movePointLeft(targetCurrency.minorUnitDigits)
            .multiply(rate).movePointRight(homeCurrency.minorUnitDigits).setScale(0, RoundingMode.HALF_UP)
            .longValueExact().takeIf { it in 0L..MONEY_MINOR_MAX }
    }.getOrNull()
}
