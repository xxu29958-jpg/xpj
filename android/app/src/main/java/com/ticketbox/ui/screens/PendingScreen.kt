package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.ExpenseCard
import com.ticketbox.ui.components.ExpensePreviewMode
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.pending.BulkConfirmEntry
import com.ticketbox.ui.screens.pending.EmptyPendingState
import com.ticketbox.ui.screens.pending.LoadingPendingState
import com.ticketbox.ui.screens.pending.NeedsReviewEmptyFilterCard
import com.ticketbox.ui.screens.pending.NeedsReviewFilter
import com.ticketbox.ui.screens.pending.NeedsReviewFilterBar
import com.ticketbox.ui.screens.pending.PendingDisplayMode
import com.ticketbox.ui.screens.pending.PendingHeader
import com.ticketbox.ui.screens.pending.PendingMessageCard
import com.ticketbox.ui.screens.pending.PendingReviewSheetHost
import com.ticketbox.ui.screens.pending.PendingToolsSheet
import com.ticketbox.ui.screens.pending.PendingTop
import com.ticketbox.ui.screens.pending.UploadFlowCard
import com.ticketbox.ui.screens.pending.UploadProgressCard
import com.ticketbox.ui.screens.pending.applyNeedsReviewFilter
import com.ticketbox.viewmodel.PendingUiState

/**
 * 待确认账单页面入口（slice 3 拆分后）。
 *
 * 仅负责：路由 → 状态 wiring → BottomSheet 派发 → 列表组装。
 * BottomSheet 内容与子组件分布在 `ui.screens.pending` 子包，
 * 业务事件全部经由 `PendingViewModel`（含 review action 扩展函数）。
 */
@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun PendingScreen(
    state: PendingUiState,
    onRefresh: () -> Unit,
    onEdit: (Expense) -> Unit,
    onConfirm: (Expense) -> Unit,
    onReject: (Expense) -> Unit,
    onKeepDuplicate: (Expense) -> Unit,
    onUploadScreenshot: () -> Unit,
    onQuickCategory: (Expense) -> Unit = {},
    onSaveQuickCategory: (Long, String) -> Unit = { _, _ -> },
    onQuickMerchant: (Expense) -> Unit = {},
    onSaveQuickMerchant: (Long, String) -> Unit = { _, _ -> },
    onMissingAmount: (Expense) -> Unit = {},
    onSaveAmountDraft: (Long, Long) -> Unit = { _, _ -> },
    onSaveAmountAndConfirm: (Long, Long) -> Unit = { _, _ -> },
    onOpenBulkConfirm: () -> Unit = {},
    onConfirmReady: () -> Unit = {},
    onOpenDuplicate: (Expense) -> Unit = {},
    onIgnoreDuplicate: (Expense) -> Unit = {},
    onCloseSheet: () -> Unit = {},
) {
    var showUploadGuide by remember { mutableStateOf(false) }
    var showPendingTools by rememberSaveable { mutableStateOf(false) }
    var displayMode by rememberSaveable { mutableStateOf(PendingDisplayMode.Compact) }
    var needsReviewFilter by rememberSaveable { mutableStateOf(NeedsReviewFilter.All) }
    var wasLoading by remember { mutableStateOf(state.loading) }
    val listState = rememberLazyListState()
    val duplicateCount = state.items.count { it.duplicateStatus == "suspected" }
    val needsAmountCount = state.items.count { it.amountCents == null }
    val needsMerchantCount = state.items.count { it.merchant.isNullOrBlank() }
    val readyToConfirmCount = state.items.count {
        it.amountCents != null && !it.merchant.isNullOrBlank() && it.duplicateStatus != "suspected"
    }
    val filteredItems = applyNeedsReviewFilter(state.items, needsReviewFilter)

    LaunchedEffect(state.loading) {
        if (wasLoading && !state.loading) {
            listState.scrollToItem(0)
        }
        wasLoading = state.loading
    }

    if (showPendingTools) {
        ModalBottomSheet(onDismissRequest = { showPendingTools = false }) {
            PendingToolsSheet(
                loading = state.loading,
                displayMode = displayMode,
                onDisplayModeChange = { displayMode = it },
                onRefresh = onRefresh,
                onDismiss = { showPendingTools = false },
            )
        }
    }

    PendingReviewSheetHost(
        sheet = state.activeSheet,
        categoryOptions = state.categoryOptions,
        actionInProgressIds = state.actionInProgressIds,
        readyCount = readyToConfirmCount,
        missingAmountSkip = needsAmountCount,
        duplicateSkip = duplicateCount,
        bulkRunning = state.bulkConfirm.running,
        onSaveQuickCategory = onSaveQuickCategory,
        onSaveQuickMerchant = onSaveQuickMerchant,
        onSaveAmountDraft = onSaveAmountDraft,
        onSaveAmountAndConfirm = onSaveAmountAndConfirm,
        onKeepBoth = onKeepDuplicate,
        onIgnoreCurrent = onIgnoreDuplicate,
        onConfirmReady = onConfirmReady,
        onDismiss = onCloseSheet,
    )

    AppScrollableContent(
        role = AppPageRole.Pending,
        isRefreshing = state.loading,
        onRefresh = onRefresh,
        listState = listState,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.cardGap),
    ) {
        item {
            PendingTop(
                pendingCount = state.items.size,
                duplicateCount = duplicateCount,
                uploading = state.uploading,
                onUploadScreenshot = onUploadScreenshot,
            )
        }

        if (state.items.isEmpty()) {
            item { UploadFlowCard() }
        }

        state.message?.let { message ->
            item { PendingMessageCard(message = message) }
        }

        if (state.uploading) {
            item { UploadProgressCard() }
        }

        when {
            state.items.isEmpty() && state.loading -> {
                item { LoadingPendingState() }
            }

            state.items.isEmpty() -> {
                item {
                    EmptyPendingState(
                        uploading = state.uploading,
                        showUploadGuide = showUploadGuide,
                        onToggleGuide = { showUploadGuide = !showUploadGuide },
                        onRefresh = onRefresh,
                    )
                }
            }

            else -> {
                item {
                    PendingHeader(
                        loading = state.loading,
                        displayMode = displayMode,
                        onOpenTools = { showPendingTools = true },
                    )
                }
                item {
                    NeedsReviewFilterBar(
                        selected = needsReviewFilter,
                        allCount = state.items.size,
                        needsAmountCount = needsAmountCount,
                        needsMerchantCount = needsMerchantCount,
                        duplicateCount = duplicateCount,
                        readyToConfirmCount = readyToConfirmCount,
                        onSelect = { needsReviewFilter = it },
                    )
                }
                if (needsReviewFilter == NeedsReviewFilter.ReadyToConfirm && readyToConfirmCount > 0) {
                    item {
                        BulkConfirmEntry(
                            readyCount = readyToConfirmCount,
                            inProgress = state.bulkConfirm.running,
                            onOpen = onOpenBulkConfirm,
                        )
                    }
                }
            }
        }

        if (state.items.isNotEmpty()) {
            if (filteredItems.isEmpty()) {
                item { NeedsReviewEmptyFilterCard(filter = needsReviewFilter) }
            } else {
                items(filteredItems, key = { it.id }) { expense ->
                    ExpenseCard(
                        expense = expense,
                        thumbnail = state.thumbnails[expense.id],
                        previewMode = when (displayMode) {
                            PendingDisplayMode.Compact -> ExpensePreviewMode.Compact
                            PendingDisplayMode.Comfortable -> ExpensePreviewMode.Comfortable
                        },
                        showActions = true,
                        actionsEnabled = expense.id !in state.actionInProgressIds,
                        onEdit = { onEdit(expense) },
                        onConfirm = {
                            when {
                                expense.amountCents == null -> onMissingAmount(expense)
                                expense.duplicateStatus == "suspected" -> onOpenDuplicate(expense)
                                expense.category.isBlank() -> onQuickCategory(expense)
                                expense.merchant.isNullOrBlank() -> onQuickMerchant(expense)
                                else -> onConfirm(expense)
                            }
                        },
                        onReject = { onReject(expense) },
                        onKeepDuplicate = { onKeepDuplicate(expense) },
                    )
                }
            }
        }
    }
}
