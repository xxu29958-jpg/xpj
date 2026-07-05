package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.ItemsSumStatus

internal enum class ExpenseDetailReconcileStatus {
    Matched,
    Diff,
    Unknown,
}

internal fun resolveExpenseDetailReconcileStatus(
    mismatchCents: Long?,
    itemsSumStatus: String? = null,
): ExpenseDetailReconcileStatus = when {
    mismatchCents == null -> ExpenseDetailReconcileStatus.Unknown
    itemsSumStatus == ItemsSumStatus.MISMATCH_KNOWN ||
        itemsSumStatus == ItemsSumStatus.MISMATCH_ACKNOWLEDGED -> ExpenseDetailReconcileStatus.Diff
    mismatchCents == 0L -> ExpenseDetailReconcileStatus.Matched
    else -> ExpenseDetailReconcileStatus.Diff
}
