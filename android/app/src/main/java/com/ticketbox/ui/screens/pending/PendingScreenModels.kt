package com.ticketbox.ui.screens.pending

import com.ticketbox.domain.model.Expense
import com.ticketbox.viewmodel.PendingListLoadState
import com.ticketbox.viewmodel.PendingSheet

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

/**
 * 上传入口的唯一槽位：任一屏幕态最多一个「上传小票」入口——
 * Content/Loading/LoadFailed 在页头（上传命令不依赖列表 query 成功，
 * 加载中或加载失败都不得夺走上传能力），settled Empty 在空态卡；
 * 只读角色没有入口。
 */
internal enum class PendingUploadEntrySlot {
    Header,
    EmptyState,
}

internal fun pendingUploadEntrySlot(
    bodyState: PendingListBodyState,
    readOnly: Boolean,
): PendingUploadEntrySlot? = when {
    readOnly -> null
    bodyState == PendingListBodyState.Empty -> PendingUploadEntrySlot.EmptyState
    else -> PendingUploadEntrySlot.Header
}

/**
 * expanded 宽度 supporting pane 的内容：无活动复核时承载 triage；
 * 有活动复核时复用现有 [PendingSheet] 状态把复核提升为常驻面板，
 * 不新造 selection/receipt owner。非 expanded 返回 null——复核继续
 * 走现有 modal sheet，supporting pane 不渲染。
 */
internal sealed interface PendingSupportingPaneContent {
    data object Triage : PendingSupportingPaneContent

    data class Review(val sheet: PendingSheet) : PendingSupportingPaneContent
}

internal fun pendingSupportingPaneContent(
    showsSupportingPane: Boolean,
    activeSheet: PendingSheet,
): PendingSupportingPaneContent? = when {
    !showsSupportingPane -> null
    activeSheet != PendingSheet.None -> PendingSupportingPaneContent.Review(activeSheet)
    else -> PendingSupportingPaneContent.Triage
}

/**
 * expanded 常驻复核面板的退出权：已有内容内取消的 sheet（QuickCategory/
 * QuickMerchant/BulkConfirm）不再获得 pane 级第二出口；缺少内容内取消的
 * MissingAmount/Duplicate 由 pane 补一个退出。任何 sheet 的在途 mutation
 * 进行中（条目 busy / 批量进行中）一律禁止退出（pane 出口与 Back 同规则），
 * 不重新打开「在途 mutation 可被隐藏」路径。
 */
internal data class PendingPaneExit(
    val showAffordance: Boolean,
    val enabled: Boolean,
)

internal fun pendingPaneExit(
    sheet: PendingSheet,
    actionInProgressIds: Set<Long>,
    bulkRunning: Boolean,
): PendingPaneExit = when (sheet) {
    PendingSheet.None -> PendingPaneExit(showAffordance = false, enabled = false)
    PendingSheet.BulkConfirm -> PendingPaneExit(showAffordance = false, enabled = !bulkRunning)
    is PendingSheet.MissingAmount -> PendingPaneExit(
        showAffordance = true,
        enabled = sheet.expense.id !in actionInProgressIds,
    )
    is PendingSheet.Duplicate -> PendingPaneExit(
        showAffordance = true,
        enabled = sheet.expense.id !in actionInProgressIds,
    )
    is PendingSheet.QuickCategory -> PendingPaneExit(
        showAffordance = false,
        enabled = sheet.expense.id !in actionInProgressIds,
    )
    is PendingSheet.QuickMerchant -> PendingPaneExit(
        showAffordance = false,
        enabled = sheet.expense.id !in actionInProgressIds,
    )
}

data class PendingScreenChromeActions(
    val onRefresh: () -> Unit,
    val onUploadScreenshot: () -> Unit,
    val onOpenRepaymentReview: () -> Unit,
    val onOpenDataQuality: () -> Unit,
    val onRetryEnrichment: () -> Unit,
    val onRetryCapacityUpload: () -> Unit,
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
