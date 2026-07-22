package com.ticketbox.ui.screens.pending

import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.FxContract
import com.ticketbox.domain.model.isUncategorizedExpenseCategory
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
    // Blocked on the exchange rate — the server confirm path 409s these rows
    // (exchange_rate_pending), so they are never a ready/confirm target.
    FxPending,
    Confirm,
}

internal data class PendingMerchantPresentation(
    val primaryText: String?,
) {
    val needsReview: Boolean = primaryText == null
}

internal fun pendingMerchantPresentation(expense: Expense): PendingMerchantPresentation {
    val primaryText = expense.merchant
        ?.trim()
        ?.takeIf(::isUsablePendingMerchantText)
    return PendingMerchantPresentation(primaryText = primaryText)
}

private fun isUsablePendingMerchantText(value: String): Boolean {
    val meaningfulCharacterCount = value.count { it.isLetterOrDigit() }
    val merchantLetterCount = value.count { it.isLetter() }
    return meaningfulCharacterCount >= 2 &&
        merchantLetterCount >= 1 &&
        !PendingTimeNoise.matches(value) &&
        !PendingDateNoise.matches(value)
}

internal fun pendingPrimaryReviewAction(expense: Expense): PendingPrimaryReviewAction = when {
    expense.amountCents == null -> PendingPrimaryReviewAction.MissingAmount
    expense.duplicateStatus == DuplicateStatusValues.SUSPECTED -> PendingPrimaryReviewAction.DuplicateReview
    pendingNeedsCategory(expense) -> PendingPrimaryReviewAction.QuickCategory
    pendingMerchantPresentation(expense).needsReview -> PendingPrimaryReviewAction.QuickMerchant
    // fx 维度与后端 ready 口径/确认守卫一致（main 的 _ensure_expense_can_confirm
    // 对 fx-pending 行抛 409）——此类行不进 ready 集、不进批量确认。
    expense.fxStatus == FxContract.StatusPending -> PendingPrimaryReviewAction.FxPending
    else -> PendingPrimaryReviewAction.Confirm
}

// 读服务端原值（serverCategory），缺省回退到展示值：归一化成「其他」的
// blank/NULL 类目在后端 missing_category 计数里，这里必须同口径可见（PR #230）。
internal fun pendingNeedsCategory(expense: Expense): Boolean =
    isUncategorizedExpenseCategory(expense.serverCategory ?: expense.category)

private val PendingTimeNoise = Regex(
    pattern = """^\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2})?(?:\s*[AP]M)?$""",
    option = RegexOption.IGNORE_CASE,
)

private val PendingDateNoise = Regex(
    pattern = """^(?:\d{4}\s*[-/.年]\s*)?\d{1,2}\s*[-/.月]\s*\d{1,2}\s*日?(?:\s+周[一二三四五六日天])?(?:\s+\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2})?)?$""",
)

data class PendingScreenChromeActions(
    val onRefresh: () -> Unit,
    val onUploadScreenshot: () -> Unit,
    val onOpenProcessing: () -> Unit,
    val onOpenRepaymentReview: () -> Unit,
    val onOpenDataQuality: () -> Unit,
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
