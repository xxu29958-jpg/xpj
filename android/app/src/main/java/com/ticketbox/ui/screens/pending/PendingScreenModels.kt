package com.ticketbox.ui.screens.pending

import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.viewmodel.PendingListLoadState

internal enum class PendingListBodyState {
    Loading,
    LoadFailed,
    Empty,
    Content,
}

internal fun pendingListBodyState(
    hasRows: Boolean,
    loadState: PendingListLoadState,
): PendingListBodyState = when {
    hasRows -> PendingListBodyState.Content
    loadState == PendingListLoadState.Loaded -> PendingListBodyState.Empty
    loadState == PendingListLoadState.Failed -> PendingListBodyState.LoadFailed
    else -> PendingListBodyState.Loading
}

internal enum class PendingPrimaryReviewAction {
    MissingAmount,
    DuplicateReview,
    QuickCategory,
    QuickMerchant,
    Confirm,
}

internal fun pendingPrimaryReviewAction(expense: Expense): PendingPrimaryReviewAction = when {
    expense.amountCents == null -> PendingPrimaryReviewAction.MissingAmount
    expense.duplicateStatus == DuplicateStatusValues.SUSPECTED -> PendingPrimaryReviewAction.DuplicateReview
    expense.category.isBlank() -> PendingPrimaryReviewAction.QuickCategory
    expense.merchant.isNullOrBlank() -> PendingPrimaryReviewAction.QuickMerchant
    else -> PendingPrimaryReviewAction.Confirm
}

data class PendingScreenChromeActions(
    val onRefresh: () -> Unit,
    val onUploadScreenshot: () -> Unit,
)

data class PendingExpenseQueueActions(
    val onEdit: (Expense) -> Unit,
    val onConfirm: (Expense) -> Unit,
    val onReject: (Expense) -> Unit,
    val onKeepDuplicate: (Expense) -> Unit,
)

data class PendingQuickFixEntryActions(
    val onQuickCategory: (Expense) -> Unit,
    val onQuickMerchant: (Expense) -> Unit,
    val onMissingAmount: (Expense) -> Unit,
)

data class PendingDuplicateReviewActions(
    val onOpenDuplicate: (Expense) -> Unit,
)

data class PendingQueueReviewActions(
    val onOpenBulkConfirm: () -> Unit,
    val onUndoReject: () -> Unit,
)

data class PendingReviewFlowActions(
    val quickFix: PendingQuickFixEntryActions,
    val duplicate: PendingDuplicateReviewActions,
    val queue: PendingQueueReviewActions,
)
