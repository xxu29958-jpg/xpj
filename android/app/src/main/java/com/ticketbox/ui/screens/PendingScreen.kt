package com.ticketbox.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.SwipeToDismissBox
import androidx.compose.material3.SwipeToDismissBoxValue
import androidx.compose.material3.Text
import androidx.compose.material3.rememberSwipeToDismissBoxState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.ExpenseCard
import com.ticketbox.ui.components.rememberAppHaptics
import com.ticketbox.ui.components.ExpensePreviewMode
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.design.AppRadius
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.pending.BulkConfirmEntry
import com.ticketbox.ui.screens.pending.EmptyPendingState
import com.ticketbox.ui.screens.pending.NeedsReviewEmptyFilterCard
import com.ticketbox.ui.screens.pending.NeedsReviewFilter
import com.ticketbox.ui.screens.pending.NeedsReviewFilterBar
import com.ticketbox.ui.screens.pending.PendingClearCelebration
import com.ticketbox.ui.screens.pending.PendingDisplayMode
import com.ticketbox.ui.screens.pending.PendingDisplayModeButton
import com.ticketbox.ui.screens.pending.PendingMessageCard
import com.ticketbox.ui.screens.pending.PendingReviewSheetHost
import com.ticketbox.ui.screens.pending.PendingToolsSheet
import com.ticketbox.ui.screens.pending.PendingTop
import com.ticketbox.ui.screens.pending.UploadFlowCard
import com.ticketbox.ui.screens.pending.UploadProgressCard
import com.ticketbox.ui.screens.pending.applyNeedsReviewFilter
import com.ticketbox.viewmodel.PendingUiState
import com.valentinilk.shimmer.shimmer

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
    val readOnly = state.readOnly
    val filteredItems = applyNeedsReviewFilter(state.items, needsReviewFilter)
    val haptics = rememberAppHaptics()
    // 待确认清零庆祝：previousItemCount > 0 → 0 时触发 1.5s 庆祝动画。
    // 用 remember 持有上一帧的 count，state 一旦回到 0 就 flip showCelebration。
    var previousItemCount by remember { mutableStateOf(state.items.size) }
    var showCelebration by remember { mutableStateOf(false) }
    LaunchedEffect(state.items.size, state.loading) {
        val nowEmpty = state.items.isEmpty() && !state.loading
        if (previousItemCount > 0 && nowEmpty) {
            showCelebration = true
            kotlinx.coroutines.delay(1800)
            showCelebration = false
        }
        previousItemCount = state.items.size
    }

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
                readOnly = readOnly,
                onUploadScreenshot = onUploadScreenshot,
                // 显示模式按钮只在列表有内容时才显示——空态用 EmptyPendingState 自带 CTA
                trailingAction = if (state.items.isNotEmpty()) {
                    {
                        PendingDisplayModeButton(
                            loading = state.loading,
                            displayMode = displayMode,
                            onClick = { showPendingTools = true },
                        )
                    }
                } else {
                    null
                },
            )
        }

        if (state.items.isEmpty() && !readOnly) {
            item { PendingClearCelebration(visible = showCelebration) }
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
                item {
                    Column(modifier = Modifier.shimmer()) {
                        repeat(5) {
                            ListItemSkeleton(horizontalPadding = 0.dp)
                        }
                    }
                }
            }

            state.items.isEmpty() -> {
                item {
                    EmptyPendingState(
                        uploading = state.uploading,
                        readOnly = readOnly,
                        showUploadGuide = showUploadGuide,
                        onToggleGuide = { showUploadGuide = !showUploadGuide },
                        onRefresh = onRefresh,
                    )
                }
            }

            else -> {
                // PendingHeader 已合并到 PendingTop 的 trailingAction —— 这里直接进 filter bar。
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
                if (!readOnly && needsReviewFilter == NeedsReviewFilter.ReadyToConfirm && readyToConfirmCount > 0) {
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
                    val canSwipe = !readOnly && expense.id !in state.actionInProgressIds
                    val dismissState = rememberSwipeToDismissBoxState(
                        confirmValueChange = { value ->
                            if (canSwipe && value == SwipeToDismissBoxValue.EndToStart) {
                                haptics.reject()
                                onReject(expense)
                                true
                            } else {
                                false
                            }
                        },
                        positionalThreshold = { totalDistance -> totalDistance * 0.5f },
                    )
                    SwipeToDismissBox(
                        modifier = Modifier.animateItem(),
                        state = dismissState,
                        enableDismissFromStartToEnd = false,
                        enableDismissFromEndToStart = canSwipe,
                        backgroundContent = { SwipeRejectBackground() },
                    ) {
                        ExpenseCard(
                            expense = expense,
                            thumbnail = state.thumbnails[expense.id],
                            previewMode = when (displayMode) {
                                PendingDisplayMode.Compact -> ExpensePreviewMode.Compact
                                PendingDisplayMode.Comfortable -> ExpensePreviewMode.Comfortable
                            },
                            showActions = !readOnly,
                            actionsEnabled = expense.id !in state.actionInProgressIds,
                            onEdit = { onEdit(expense) },
                            onConfirm = {
                                when {
                                    expense.amountCents == null -> onMissingAmount(expense)
                                    expense.duplicateStatus == "suspected" -> onOpenDuplicate(expense)
                                    expense.category.isBlank() -> onQuickCategory(expense)
                                    expense.merchant.isNullOrBlank() -> onQuickMerchant(expense)
                                    else -> {
                                        haptics.confirm()
                                        onConfirm(expense)
                                    }
                                }
                            },
                            onReject = {
                                haptics.reject()
                                onReject(expense)
                            },
                            onKeepDuplicate = { onKeepDuplicate(expense) },
                        )
                    }
                }
            }
        }
    }
}

@Composable
private fun SwipeRejectBackground() {
    val visuals = MaterialTheme.colorScheme
    Box(
        modifier = Modifier
            .fillMaxSize()
            .padding(vertical = AppSpacing.tinyGap)
            .clip(RoundedCornerShape(AppRadius.medium))
            .background(visuals.errorContainer)
            .padding(horizontal = AppSpacing.cardPaddingSmall),
        contentAlignment = Alignment.CenterEnd,
    ) {
        androidx.compose.foundation.layout.Row(
            verticalAlignment = Alignment.CenterVertically,
            horizontalArrangement = Arrangement.spacedBy(8.dp),
        ) {
            Text(
                text = "忽略",
                color = visuals.onErrorContainer,
                style = MaterialTheme.typography.labelLarge,
            )
            Icon(
                imageVector = Icons.Filled.DeleteOutline,
                contentDescription = null,
                tint = visuals.onErrorContainer,
            )
        }
    }
}
