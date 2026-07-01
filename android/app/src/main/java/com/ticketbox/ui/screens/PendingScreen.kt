package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.DeleteOutline
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.unit.dp
import com.ticketbox.R
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.isPendingReadyToConfirmDirectly
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.rememberAppHaptics
import com.ticketbox.ui.components.ListItemSkeleton
import com.ticketbox.ui.components.SwipeActionConfig
import com.ticketbox.ui.components.SwipeableActionRow
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalSwipeActionTokens
import com.ticketbox.ui.screens.pending.EmptyPendingState
import com.ticketbox.ui.screens.pending.NeedsReviewEmptyFilterCard
import com.ticketbox.ui.screens.pending.NeedsReviewFilter
import com.ticketbox.ui.screens.pending.NeedsReviewFilterBar
import com.ticketbox.ui.screens.pending.PendingClearCelebration
import com.ticketbox.ui.screens.pending.PendingDisplayMode
import com.ticketbox.ui.screens.pending.PendingDisplayModeButton
import com.ticketbox.ui.screens.pending.PendingExpenseReviewActions
import com.ticketbox.ui.screens.pending.PendingExpenseReviewItem
import com.ticketbox.ui.screens.pending.PendingExpenseReviewRow
import com.ticketbox.ui.screens.pending.PendingMessageCard
import com.ticketbox.ui.screens.pending.PendingQueueCounts
import com.ticketbox.ui.screens.pending.PendingQueueOverview
import com.ticketbox.ui.screens.pending.PendingUndoRejectBanner
import com.ticketbox.ui.screens.pending.PendingReviewSheetHost
import com.ticketbox.ui.screens.pending.PendingToolsSheet
import com.ticketbox.ui.screens.pending.PendingTop
import com.ticketbox.ui.screens.pending.UploadProgressCard
import com.ticketbox.ui.screens.pending.applyNeedsReviewFilter
import com.ticketbox.viewmodel.PendingUiState
import com.valentinilk.shimmer.shimmer

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
    onSkipReviewField: () -> Unit = {},
    onCloseSheet: () -> Unit = {},
    onUndoReject: () -> Unit = {},
) {
    var showUploadGuide by remember { mutableStateOf(false) }
    var showPendingTools by rememberSaveable { mutableStateOf(false) }
    var displayMode by rememberSaveable { mutableStateOf(PendingDisplayMode.Compact) }
    var needsReviewFilter by rememberSaveable { mutableStateOf(NeedsReviewFilter.All) }
    var wasLoading by remember { mutableStateOf(state.loading) }
    val blockingRefresh = state.showPageRefresh
    val listState = rememberLazyListState()
    val queueCounts = PendingQueueCounts(
        all = state.items.size,
        needsAmount = state.items.count { it.amountCents == null },
        needsMerchant = state.items.count { it.merchant.isNullOrBlank() },
        duplicate = state.items.count { it.duplicateStatus == DuplicateStatusValues.SUSPECTED },
        readyToConfirm = state.items.count { it.isPendingReadyToConfirmDirectly() },
    )
    val readOnly = state.readOnly
    val filteredItems = applyNeedsReviewFilter(state.items, needsReviewFilter)
    val haptics = rememberAppHaptics()

    fun resolvePrimaryAction(expense: Expense) {
        when {
            expense.amountCents == null -> onMissingAmount(expense)
            expense.duplicateStatus == DuplicateStatusValues.SUSPECTED -> onOpenDuplicate(expense)
            expense.category.isBlank() -> onQuickCategory(expense)
            expense.merchant.isNullOrBlank() -> onQuickMerchant(expense)
            else -> {
                haptics.confirm()
                onConfirm(expense)
            }
        }
    }

    // Trigger celebration only when a settled non-loading queue goes from non-empty to empty.
    var previousItemCount by remember { mutableStateOf(if (state.loading) 0 else state.items.size) }
    var showCelebration by remember { mutableStateOf(false) }
    LaunchedEffect(state.items.size, state.loading) {
        if (state.loading) return@LaunchedEffect
        if (previousItemCount > 0 && state.items.isEmpty()) {
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
                loading = blockingRefresh,
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
        readyCount = queueCounts.readyToConfirm,
        missingAmountSkip = queueCounts.needsAmount,
        duplicateSkip = queueCounts.duplicate,
        bulkRunning = state.bulkConfirm.running,
        bulkConfirmed = state.bulkConfirm.succeeded,
        bulkTotal = state.bulkConfirm.total,
        reviewRemaining = state.reviewRemaining,
        statusMessage = state.message?.asString(),
        onSaveQuickCategory = onSaveQuickCategory,
        onSaveQuickMerchant = onSaveQuickMerchant,
        onSaveAmountDraft = onSaveAmountDraft,
        onSaveAmountAndConfirm = onSaveAmountAndConfirm,
        onSkipReviewField = onSkipReviewField,
        onKeepBoth = onKeepDuplicate,
        onIgnoreCurrent = onIgnoreDuplicate,
        onConfirmReady = onConfirmReady,
        onDismiss = onCloseSheet,
    )

    AppScrollableContent(
        role = AppPageRole.Pending,
        isRefreshing = state.showPageRefresh,
        onRefresh = onRefresh,
        listState = listState,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.contentGap),
    ) {
        item {
            PendingTop(
                counts = queueCounts,
                uploading = state.uploading,
                readOnly = readOnly,
                onUploadScreenshot = onUploadScreenshot,
                trailingAction = if (state.items.isNotEmpty()) {
                    {
                        PendingDisplayModeButton(
                            loading = blockingRefresh,
                            displayMode = displayMode,
                            onClick = { showPendingTools = true },
                        )
                    }
                } else {
                    null
                },
            )
        }

        val authorityTone = when {
            readOnly -> DataAuthorityTone.ReadOnly
            blockingRefresh -> DataAuthorityTone.Refreshing
            state.showingCachedSnapshot -> DataAuthorityTone.LocalCache
            else -> DataAuthorityTone.Backend
        }
        if (authorityTone != DataAuthorityTone.Backend) {
            item {
                AppDataAuthorityStrip(
                    tone = authorityTone,
                    localCacheBodyRes = R.string.components_data_authority_pending_cache_body,
                )
            }
        }

        if (state.items.isNotEmpty()) {
            item {
                PendingQueueOverview(
                    counts = queueCounts,
                    readOnly = readOnly,
                    bulkRunning = state.bulkConfirm.running,
                    onOpenBulkConfirm = onOpenBulkConfirm,
                )
            }
        }

        if (state.items.isEmpty() && !readOnly) {
            item { PendingClearCelebration(visible = showCelebration) }
        }

        state.undoableExpense?.let { undoable ->
            item(key = "undo-${undoable.id}") {
                PendingUndoRejectBanner(expense = undoable, onUndo = onUndoReject)
            }
        }

        state.message?.let { message ->
            item { PendingMessageCard(message = message.asString()) }
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
                item {
                    NeedsReviewFilterBar(
                        selected = needsReviewFilter,
                        counts = queueCounts,
                        onSelect = { needsReviewFilter = it },
                    )
                }
            }
        }

        if (state.items.isNotEmpty()) {
            if (filteredItems.isEmpty()) {
                item { NeedsReviewEmptyFilterCard(filter = needsReviewFilter) }
            } else {
                items(filteredItems, key = { it.id }) { expense ->
                    val actionBusy = expense.id in state.actionInProgressIds
                    val canSwipe = !readOnly && !actionBusy
                    val showInlineActions = !readOnly && displayMode == PendingDisplayMode.Comfortable
                    val swipeTokens = LocalSwipeActionTokens.current
                    val leftAction = if (canSwipe) SwipeActionConfig(
                        icon = Icons.Filled.CheckCircle,
                        label = stringResource(R.string.pending_swipe_confirm_label),
                        bg = swipeTokens.confirm.bg,
                        fg = swipeTokens.confirm.fg,
                        onTriggered = { resolvePrimaryAction(expense) },
                    ) else null
                    val rightAction = if (canSwipe) SwipeActionConfig(
                        icon = Icons.Filled.DeleteOutline,
                        label = stringResource(R.string.pending_swipe_ignore_label),
                        bg = swipeTokens.ignore.bg,
                        fg = swipeTokens.ignore.fg,
                        onTriggered = { onReject(expense) },
                    ) else null
                    SwipeableActionRow(
                        modifier = Modifier.animateItem(),
                        leftAction = leftAction,
                        rightAction = rightAction,
                        enabled = canSwipe,
                    ) {
                        PendingExpenseReviewRow(
                            item = PendingExpenseReviewItem(
                                expense = expense,
                                thumbnail = state.thumbnails[expense.id],
                                compact = displayMode == PendingDisplayMode.Compact,
                                showInlineActions = showInlineActions,
                                busy = actionBusy,
                            ),
                            actions = PendingExpenseReviewActions(
                                canMutate = canSwipe,
                                onEdit = { onEdit(expense) },
                                onPrimaryAction = { resolvePrimaryAction(expense) },
                                onReject = {
                                    haptics.reject()
                                    onReject(expense)
                                },
                                onKeepDuplicate = { onKeepDuplicate(expense) },
                            ),
                        )
                    }
                }
            }
        }
    }
}
