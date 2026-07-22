package com.ticketbox.ui.screens.pending

import androidx.annotation.StringRes
import com.ticketbox.R
import com.ticketbox.domain.model.Expense

@StringRes
internal fun pendingPrimaryActionLabelRes(expense: Expense): Int = when (pendingPrimaryReviewAction(expense)) {
    PendingPrimaryReviewAction.MissingAmount -> R.string.pending_row_action_amount
    PendingPrimaryReviewAction.DuplicateReview -> R.string.pending_row_action_duplicate
    PendingPrimaryReviewAction.QuickCategory -> R.string.pending_row_action_category
    PendingPrimaryReviewAction.QuickMerchant -> R.string.pending_row_action_merchant
    PendingPrimaryReviewAction.FxPending -> R.string.pending_row_action_fx_pending
    PendingPrimaryReviewAction.Confirm -> R.string.pending_row_action_confirm
}
