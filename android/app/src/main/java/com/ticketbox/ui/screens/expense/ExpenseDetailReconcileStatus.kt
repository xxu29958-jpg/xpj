package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.ItemsSumStatus

internal enum class ExpenseDetailReconcileStatus {
    Matched,
    Diff,
    Partial,
    Overallocated,
    Unknown,
}

internal fun resolveExpenseDetailReconcileStatus(
    mismatchCents: Long?,
    itemsSumStatus: String? = null,
    partialIsValid: Boolean = false,
): ExpenseDetailReconcileStatus = when {
    mismatchCents == null -> ExpenseDetailReconcileStatus.Unknown
    itemsSumStatus == ItemsSumStatus.MISMATCH_KNOWN ||
        itemsSumStatus == ItemsSumStatus.MISMATCH_ACKNOWLEDGED -> ExpenseDetailReconcileStatus.Diff
    mismatchCents == 0L -> ExpenseDetailReconcileStatus.Matched
    partialIsValid && mismatchCents > 0L -> ExpenseDetailReconcileStatus.Partial
    partialIsValid -> ExpenseDetailReconcileStatus.Overallocated
    else -> ExpenseDetailReconcileStatus.Diff
}
