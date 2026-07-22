package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.DuplicateStatusValues
import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppAdaptivePaneScaffold
import com.ticketbox.ui.components.AppAdaptivePanePurpose
import com.ticketbox.ui.components.AppAdaptivePaneStructures
import com.ticketbox.ui.components.AppAdaptiveSupportingPane
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.AppErrorState
import com.ticketbox.ui.components.AppListStateContent
import com.ticketbox.ui.components.AppListStateSpec
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.AppScrollableContent
import com.ticketbox.ui.components.AppScrollableContentChrome
import com.ticketbox.ui.components.AppScrollableContentLayout
import com.ticketbox.ui.components.AppScrollableRefreshState
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.components.appAdaptiveSupportingPaneContent
import com.ticketbox.ui.components.rememberAppHaptics
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.screens.pending.EmptyPendingState
import com.ticketbox.ui.screens.pending.EmptyPendingStateModel
import com.ticketbox.ui.screens.pending.InboxSection
import com.ticketbox.ui.screens.pending.InboxActionLinks
import com.ticketbox.ui.screens.pending.InboxSectionNavigation
import com.ticketbox.ui.screens.pending.NeedsReviewEmptyFilterCard
import com.ticketbox.ui.screens.pending.NeedsReviewFilter
import com.ticketbox.ui.screens.pending.NeedsReviewFilterBar
import com.ticketbox.ui.screens.pending.NeedsReviewFilterBarState
import com.ticketbox.ui.screens.pending.PendingClearCelebration
import com.ticketbox.ui.screens.pending.PendingDisplayMode
import com.ticketbox.ui.screens.pending.PendingDisplayModeButton
import com.ticketbox.ui.screens.pending.PendingExpenseQueueActions
import com.ticketbox.ui.screens.pending.PendingExpenseReviewActions
import com.ticketbox.ui.screens.pending.PendingExpenseReviewItem
import com.ticketbox.ui.screens.pending.PendingExpenseReviewRow
import com.ticketbox.ui.screens.pending.PendingMessageCard
import com.ticketbox.ui.screens.pending.PendingListBodyState
import com.ticketbox.ui.screens.pending.PendingPrimaryReviewAction
import com.ticketbox.ui.screens.pending.PendingQueueCounts
import com.ticketbox.ui.screens.pending.PendingQueueEvidence
import com.ticketbox.ui.screens.pending.PendingQueueOverview
import com.ticketbox.ui.screens.pending.PendingReviewFlowActions
import com.ticketbox.ui.screens.pending.PendingUndoRejectBanner
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostActions
import com.ticketbox.ui.screens.pending.PendingReviewSheetHost
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostState
import com.ticketbox.ui.screens.pending.PendingScreenChromeActions
import com.ticketbox.ui.screens.pending.PendingToolsSheet
import com.ticketbox.ui.screens.pending.PendingTop
import com.ticketbox.ui.screens.pending.PendingTopState
import com.ticketbox.ui.screens.pending.UploadProgressCard
import com.ticketbox.ui.screens.pending.applyNeedsReviewFilter
import com.ticketbox.ui.screens.pending.pendingPrimaryReviewAction
import com.ticketbox.ui.screens.pending.pendingMerchantPresentation
import com.ticketbox.ui.screens.pending.pendingNeedsCategory
import com.ticketbox.ui.screens.pending.pendingListBodyState
import com.ticketbox.ui.screens.pending.shouldShowNeedsReviewFilterBar
import com.ticketbox.viewmodel.PendingUiState

@Composable
@OptIn(ExperimentalMaterial3Api::class)
fun PendingScreen(
    state: PendingUiState,
    chromeActions: PendingScreenChromeActions,
    itemActions: PendingExpenseQueueActions,
    reviewActions: PendingReviewFlowActions,
    sheetActions: PendingReviewSheetHostActions,
) {
    var showUploadGuide by remember { mutableStateOf(false) }
    var showPendingTools by rememberSaveable { mutableStateOf(false) }
    var displayMode by rememberSaveable { mutableStateOf(PendingDisplayMode.Compact) }
    var needsReviewFilter by rememberSaveable { mutableStateOf(NeedsReviewFilter.All) }
    val blockingRefresh = state.showPageRefresh
    var wasBlockingRefresh by remember { mutableStateOf(blockingRefresh) }
    val listState = rememberLazyListState()
    val queueCounts = PendingQueueCounts(
        all = state.items.size,
        needsAmount = state.items.count { it.amountCents == null },
        needsMerchant = state.items.count { pendingMerchantPresentation(it).needsReview },
        duplicate = state.items.count { it.duplicateStatus == DuplicateStatusValues.SUSPECTED },
        readyToConfirm = state.items.count {
            pendingPrimaryReviewAction(it) == PendingPrimaryReviewAction.Confirm
        },
        needsCategory = state.items.count(::pendingNeedsCategory),
        needsInformation = state.items.count { expense ->
            pendingPrimaryReviewAction(expense) in PendingInformationActions
        },
    )
    val readOnly = state.readOnly
    val filteredItems = applyNeedsReviewFilter(state.items, needsReviewFilter)
    val bodyState = pendingListBodyState(
        hasRows = state.items.isNotEmpty(),
        loadState = state.listLoadState,
    )
    val haptics = rememberAppHaptics()
    val adaptivePolicy = LocalAppAdaptiveLayoutPolicy.current
    val authorityTone = when {
        readOnly -> DataAuthorityTone.ReadOnly
        blockingRefresh -> DataAuthorityTone.Refreshing
        state.showingCachedSnapshot -> DataAuthorityTone.LocalCache
        else -> DataAuthorityTone.Backend
    }
    val triagePaneState = PendingTriagePaneState(
        counts = queueCounts,
        selectedFilter = needsReviewFilter,
        authorityTone = authorityTone,
        queueEvidence = if (state.showingCachedSnapshot) {
            PendingQueueEvidence.LocalCache
        } else {
            PendingQueueEvidence.Backend
        },
        readOnly = readOnly,
        bulkRunning = state.bulkConfirm.running,
        showNeedsReviewFilter = bodyState == PendingListBodyState.Content &&
            shouldShowNeedsReviewFilterBar(queueCounts, needsReviewFilter),
    )
    val triagePaneActions = PendingTriagePaneActions(
        onSelectFilter = { needsReviewFilter = it },
        onOpenProcessing = chromeActions.onOpenProcessing,
        onOpenRepaymentReview = chromeActions.onOpenRepaymentReview,
        onOpenDataQuality = chromeActions.onOpenDataQuality,
        onOpenBulkConfirm = reviewActions.queue.onOpenBulkConfirm,
    )

    fun resolvePrimaryAction(expense: Expense) {
        when (pendingPrimaryReviewAction(expense)) {
            PendingPrimaryReviewAction.MissingAmount -> reviewActions.quickFix.onMissingAmount(expense)
            PendingPrimaryReviewAction.DuplicateReview -> reviewActions.duplicate.onOpenDuplicate(expense)
            PendingPrimaryReviewAction.QuickCategory -> reviewActions.quickFix.onQuickCategory(expense)
            PendingPrimaryReviewAction.QuickMerchant -> reviewActions.quickFix.onQuickMerchant(expense)
            // 待汇率行不可确认（服务端 409），主操作落到编辑页查看/处理汇率上下文。
            PendingPrimaryReviewAction.FxPending -> itemActions.onEdit(expense)
            PendingPrimaryReviewAction.Confirm -> {
                haptics.confirm()
                itemActions.onConfirm(expense)
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

    LaunchedEffect(blockingRefresh) {
        if (wasBlockingRefresh && !blockingRefresh) {
            listState.scrollToItem(0)
        }
        wasBlockingRefresh = blockingRefresh
    }

    LaunchedEffect(chromeActions.requestedFilter) {
        chromeActions.requestedFilter?.let { requested ->
            needsReviewFilter = requested
            listState.scrollToItem(0)
            chromeActions.onRequestedFilterConsumed()
        }
    }

    if (showPendingTools) {
        ModalBottomSheet(onDismissRequest = { showPendingTools = false }) {
            PendingToolsSheet(
                loading = blockingRefresh,
                displayMode = displayMode,
                onDisplayModeChange = { displayMode = it },
                onRefresh = chromeActions.onRefresh,
                onDismiss = { showPendingTools = false },
            )
        }
    }

    PendingReviewSheetHost(
        state = PendingReviewSheetHostState(
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
        ),
        actions = sheetActions,
    )

    AppAdaptivePaneScaffold(
        structure = AppAdaptivePaneStructures.Inbox,
        policy = adaptivePolicy,
        primaryPane = {
            AppScrollableContent(
                chrome = AppScrollableContentChrome(
                    role = AppPageRole.Pending,
                    layout = AppScrollableContentLayout(
                        horizontalPadding = AppSpacing.cardPaddingSmall,
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                    ),
                ),
                refresh = AppScrollableRefreshState(
                    isRefreshing = state.showPageRefresh,
                    onRefresh = chromeActions.onRefresh,
                ),
                listState = listState,
            ) {
                item {
                    PendingTop(
                        state = PendingTopState(
                            counts = queueCounts,
                            uploading = state.uploading,
                            readOnly = readOnly,
                        ),
                        onUploadScreenshot = chromeActions.onUploadScreenshot,
                        trailingAction = if (state.items.isNotEmpty()) {
                            {
                                PendingDisplayModeButton(
                                    loading = blockingRefresh,
                                    onClick = { showPendingTools = true },
                                )
                            }
                        } else {
                            null
                        },
                    )
                }
                if (!adaptivePolicy.showsSupportingPane) {
                    item {
                        PendingTriagePane(
                            state = triagePaneState,
                            actions = triagePaneActions,
                        )
                    }
                }

        if (state.items.isEmpty() && !readOnly) {
            item { PendingClearCelebration(visible = showCelebration) }
        }

        state.undoableExpense?.let { undoable ->
            item(key = "undo-${undoable.id}") {
                PendingUndoRejectBanner(expense = undoable, onUndo = reviewActions.queue.onUndoReject)
            }
        }

        state.message?.takeIf { bodyState != PendingListBodyState.LoadFailed }?.let { message ->
            item { PendingMessageCard(message = message.asString()) }
        }

        if (state.uploading) {
            item { UploadProgressCard() }
        }

        when {
            bodyState == PendingListBodyState.Loading -> {
                item {
                    AppListStateContent(
                        state = AppListStateSpec(
                            isEmpty = true,
                            loading = true,
                            emptyText = stringResource(R.string.pending_empty_card_body_loading),
                            skeletonRows = 5,
                        ),
                    ) {}
                }
            }

            bodyState == PendingListBodyState.LoadFailed -> {
                item {
                    AppErrorState(
                        title = stringResource(R.string.pending_load_failed_title),
                        body = stringResource(R.string.pending_load_failed_body),
                        onRetry = chromeActions.onRefresh,
                    )
                }
            }

            bodyState == PendingListBodyState.Empty -> {
                item {
                    EmptyPendingState(
                        state = EmptyPendingStateModel(
                            uploading = state.uploading,
                            loading = state.loading,
                            readOnly = readOnly,
                            showUploadGuide = showUploadGuide,
                        ),
                        onToggleGuide = { showUploadGuide = !showUploadGuide },
                        onRefresh = chromeActions.onRefresh,
                    )
                }
            }

            bodyState == PendingListBodyState.Content -> Unit
        }

        if (state.items.isNotEmpty()) {
            if (filteredItems.isEmpty()) {
                item { NeedsReviewEmptyFilterCard(filter = needsReviewFilter) }
            } else {
                items(filteredItems, key = { it.id }) { expense ->
                    val actionBusy = expense.id in state.actionInProgressIds
                    val canMutate = !readOnly && !actionBusy
                    val showInlineActions = !readOnly && displayMode == PendingDisplayMode.Comfortable
                    PendingExpenseReviewRow(
                        item = PendingExpenseReviewItem(
                            expense = expense,
                            thumbnail = state.thumbnails[expense.id],
                            compact = displayMode == PendingDisplayMode.Compact,
                            showInlineActions = showInlineActions,
                            busy = actionBusy,
                        ),
                        actions = PendingExpenseReviewActions(
                            canMutate = canMutate,
                            onEdit = { itemActions.onEdit(expense) },
                            onPrimaryAction = { resolvePrimaryAction(expense) },
                            onReject = {
                                haptics.reject()
                                itemActions.onReject(expense)
                            },
                            onKeepDuplicate = { itemActions.onKeepDuplicate(expense) },
                        ),
                        modifier = Modifier.animateItem(),
                    )
                }
            }
        }
            }
        },
        supportingPane = appAdaptiveSupportingPaneContent(
            purpose = AppAdaptivePanePurpose.IntakeAndTriage,
        ) {
            AppAdaptiveSupportingPane(
                role = AppPageRole.Pending,
                verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
            ) {
                PendingTriagePane(
                    state = triagePaneState,
                    actions = triagePaneActions,
                )
            }
        },
    )
}

private data class PendingTriagePaneState(
    val counts: PendingQueueCounts,
    val selectedFilter: NeedsReviewFilter,
    val authorityTone: DataAuthorityTone,
    val queueEvidence: PendingQueueEvidence,
    val readOnly: Boolean,
    val bulkRunning: Boolean,
    val showNeedsReviewFilter: Boolean,
)

private data class PendingTriagePaneActions(
    val onSelectFilter: (NeedsReviewFilter) -> Unit,
    val onOpenProcessing: () -> Unit,
    val onOpenRepaymentReview: () -> Unit,
    val onOpenDataQuality: () -> Unit,
    val onOpenBulkConfirm: () -> Unit,
)

@Composable
private fun PendingTriagePane(
    state: PendingTriagePaneState,
    actions: PendingTriagePaneActions,
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        PendingQueueOverview(
            counts = state.counts,
            evidence = state.queueEvidence,
            readOnly = state.readOnly,
            bulkRunning = state.bulkRunning,
            onOpenBulkConfirm = actions.onOpenBulkConfirm,
        )
        InboxSectionNavigation(
            selected = if (state.selectedFilter == NeedsReviewFilter.Duplicate) {
                InboxSection.Duplicates
            } else {
                InboxSection.Pending
            },
            onSelect = { section ->
                actions.onSelectFilter(
                    when (section) {
                        InboxSection.Pending -> NeedsReviewFilter.All
                        InboxSection.Duplicates -> NeedsReviewFilter.Duplicate
                    },
                )
            },
        )
        InboxActionLinks(
            onOpenProcessing = actions.onOpenProcessing,
            onOpenRepaymentReview = actions.onOpenRepaymentReview,
            onOpenDataQuality = actions.onOpenDataQuality,
        )
        if (state.authorityTone != DataAuthorityTone.Backend) {
            AppDataAuthorityStrip(
                tone = state.authorityTone,
                localCacheBodyRes = R.string.components_data_authority_pending_cache_body,
            )
        }
        if (state.showNeedsReviewFilter) {
            NeedsReviewFilterBar(
                state = NeedsReviewFilterBarState(
                    selected = state.selectedFilter,
                    counts = state.counts,
                ),
                onSelect = actions.onSelectFilter,
            )
        }
    }
}

private val PendingInformationActions = setOf(
    PendingPrimaryReviewAction.MissingAmount,
    PendingPrimaryReviewAction.QuickCategory,
    PendingPrimaryReviewAction.QuickMerchant,
)
