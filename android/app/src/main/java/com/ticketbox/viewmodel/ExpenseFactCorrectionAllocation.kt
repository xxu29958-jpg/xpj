package com.ticketbox.viewmodel

import com.ticketbox.data.repository.projectCorrection
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.domain.model.ExpenseSplits

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
    val projected = expense.projectCorrection(draft.copy(items = null, splits = null))
    draft.amountCents?.let { explicitHomeAmount ->
        return projected.amountCents.takeIf { it == explicitHomeAmount }
    }
    val targetCurrency = draft.originalCurrencyCode ?: return null
    val targetAmount = draft.originalAmountMinor ?: return null
    if (projected.originalCurrencyCode != targetCurrency || projected.originalAmountMinor != targetAmount) {
        return null
    }
    return projected.amountCents
}
