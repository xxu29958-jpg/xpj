package com.ticketbox.ui.screens.pending

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense

@StringRes
internal fun pendingPrimaryActionLabelRes(expense: Expense): Int = when {
    expense.amountCents == null -> R.string.pending_row_action_amount
    expense.duplicateStatus == DuplicateStatusValues.SUSPECTED -> R.string.pending_row_action_duplicate
    expense.category.isBlank() -> R.string.pending_row_action_category
    expense.merchant.isNullOrBlank() -> R.string.pending_row_action_merchant
    else -> R.string.pending_row_action_confirm
}
