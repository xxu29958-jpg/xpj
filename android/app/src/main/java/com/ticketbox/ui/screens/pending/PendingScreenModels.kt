package com.ticketbox.ui.screens.pending

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

data class PendingScreenChromeActions(
    val onRefresh: () -> Unit,
    val onUploadScreenshot: () -> Unit,
    val onOpenRepaymentReview: () -> Unit,
    val onOpenDataQuality: () -> Unit,
    val onRetryEnrichment: () -> Unit,
    val requestedFilter: NeedsReviewFilter? = null,
    val onRequestedFilterConsumed: () -> Unit = {},
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
