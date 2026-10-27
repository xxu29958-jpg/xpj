package com.ticketbox.ui.screens

import com.ticketbox.viewmodel.reviewExpense
import com.ticketbox.viewmodel.reviewInputKey

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.itemsIndexed
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.activity.compose.BackHandler
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.rememberModalBottomSheetState
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
import com.ticketbox.ui.components.expenseAccountingDayLabel
import com.ticketbox.presentation.displayCalendarDay
import com.ticketbox.ui.design.AppAdaptiveContentWidth
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.design.LocalAppAdaptiveLayoutPolicy
import com.ticketbox.ui.screens.pending.EmptyPendingState
import com.ticketbox.ui.screens.pending.EmptyPendingStateModel
import com.ticketbox.ui.screens.pending.InboxActionLinks
import com.ticketbox.ui.screens.pending.NeedsReviewEmptyFilterCard
import com.ticketbox.ui.screens.pending.NeedsReviewFilter
import com.ticketbox.ui.screens.pending.NeedsReviewFilterBar
import com.ticketbox.ui.screens.pending.NeedsReviewFilterBarState
import com.ticketbox.ui.screens.pending.PendingClearCelebration
import com.ticketbox.ui.screens.pending.PendingDisplayMode
import com.ticketbox.ui.screens.pending.PendingDisplayModeButton
import com.ticketbox.ui.screens.pending.PendingEnrichmentStatusBand
import com.ticketbox.ui.screens.pending.PendingExpenseQueueActions
import com.ticketbox.ui.screens.pending.PendingExpenseReviewActions
import com.ticketbox.ui.screens.pending.PendingExpenseReviewItem
import com.ticketbox.ui.screens.pending.PendingExpenseReviewRow
import com.ticketbox.ui.screens.pending.PendingMessageCard
import com.ticketbox.ui.screens.pending.PendingCaptureSheet
import com.ticketbox.ui.screens.pending.PendingListBodyState
import com.ticketbox.ui.screens.pending.PendingQueueCounts
import com.ticketbox.ui.screens.pending.PendingQueueEvidence
import com.ticketbox.ui.screens.pending.PendingQueueOverview
import com.ticketbox.ui.screens.pending.PendingReviewFlowActions
import com.ticketbox.ui.screens.pending.PendingUndoRejectBanner
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostActions
import com.ticketbox.ui.screens.pending.PendingReviewSheetHost
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostState
import com.ticketbox.ui.screens.pending.PendingSupportingPaneBody
import com.ticketbox.ui.screens.pending.PendingSupportingPaneContent
import com.ticketbox.ui.screens.pending.pendingSupportingPaneContent
import com.ticketbox.ui.screens.pending.pendingPaneExit
import com.ticketbox.ui.screens.pending.PendingScreenChromeActions
import com.ticketbox.ui.screens.pending.PendingToolsSheet
import com.ticketbox.ui.screens.pending.PendingTop
import com.ticketbox.ui.screens.pending.PendingTopState
import com.ticketbox.ui.screens.settings.SettingsEntryRow
import com.ticketbox.ui.screens.pending.applyNeedsReviewFilter
import com.ticketbox.domain.model.PendingPrimaryReviewAction
import com.ticketbox.domain.model.pendingPrimaryReviewAction
import com.ticketbox.domain.model.pendingMerchantPresentation
import com.ticketbox.domain.model.pendingNeedsCategory
import com.ticketbox.ui.screens.pending.pendingListBodyState
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
    var showCapture by rememberSaveable { mutableStateOf(false) }
    LaunchedEffect(chromeActions.uploadSelection.selectionId) {
        if (chromeActions.uploadSelection.pendingCount > 0) showCapture = true
    }
    var displayMode by rememberSaveable { mutableStateOf(PendingDisplayMode.Compact) }
    var needsReviewFilter by rememberSaveable { mutableStateOf(NeedsReviewFilter.All) }
    val blockingRefresh = state.showPageRefresh
    var wasBlockingRefresh by remember { mutableStateOf(blockingRefresh) }
    val listState = rememberLazyListState()
    val queueCounts = PendingQueueCounts(
        all = state.items.size,
        needsAmount = state.items.count { com.ticketbox.domain.model.pendingNeedsAmount(it) },
        needsFx = state.items.count { com.ticketbox.domain.model.pendingNeedsFx(it) },
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
    // Both the feedback and its navigation belong to the current pending expense.
    val enrichmentTarget = state.enrichment.feedback?.let { feedback ->
        state.items.firstOrNull { it.id == feedback.expenseId }
    }
    val bodyState = pendingListBodyState(
        hasRows = state.items.isNotEmpty(),
        loadState = state.listLoadState,
    )
    val messageCardText = state.message?.asString()
    val haptics = rememberAppHaptics()
    val adaptivePolicy = LocalAppAdaptiveLayoutPolicy.current
    val supportingContent = pendingSupportingPaneContent(
        showsSupportingPane = adaptivePolicy.showsSupportingPane,
        activeSheet = state.activeSheet,
    )
    // 复核常驻 pane 时，队列只标出 pane 正在核对的那一行；开始核对已经发生，不再给第二个入口。
    val paneReviewExpenseId = (supportingContent as? PendingSupportingPaneContent.Review)?.sheet?.reviewExpense()?.id
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
    )
    val triagePaneActions = PendingTriagePaneActions(
        onSelectFilter = { needsReviewFilter = it },
        onOpenRepaymentReview = chromeActions.onOpenRepaymentReview,
        onOpenDataQuality = chromeActions.onOpenDataQuality,
        onOpenBulkConfirm = reviewActions.queue.onOpenBulkConfirm,
    )

    fun resolvePrimaryAction(expense: Expense) {
        if (readOnly && expense.duplicateStatus == DuplicateStatusValues.SUSPECTED) {
            reviewActions.duplicate.onOpenDuplicate(expense)
            return
        }
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

    val reviewTarget = filteredItems.firstOrNull {
        it.id !in state.actionInProgressIds && pendingPrimaryReviewAction(it) != PendingPrimaryReviewAction.Confirm
    } ?: filteredItems.firstOrNull { it.id !in state.actionInProgressIds }
    val onStartReview: (() -> Unit)? = if (readOnly || state.bulkConfirm.running || reviewTarget == null) null else {
        {
            if (pendingPrimaryReviewAction(reviewTarget) == PendingPrimaryReviewAction.Confirm) {
                itemActions.onEdit(reviewTarget)
            } else resolvePrimaryAction(reviewTarget)
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
        ModalBottomSheet(
            onDismissRequest = { showPendingTools = false },
            sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true),
        ) {
            PendingToolsSheet(
                state = com.ticketbox.ui.screens.pending.PendingToolsState(blockingRefresh, displayMode),
                onDisplayModeChange = { displayMode = it },
                actions = chromeActions,
                queue = com.ticketbox.ui.screens.pending.PendingToolsQueueActions(
                    onOpenCapture = { showCapture = true },
                    onStartReview = onStartReview,
                    onOpenBulkConfirm = if (!readOnly && !state.bulkConfirm.running &&
                        com.ticketbox.ui.screens.pending.pendingQueueOverviewModel(queueCounts, triagePaneState.queueEvidence).canBulkConfirm
                    ) reviewActions.queue.onOpenBulkConfirm else null,
                ),
                onDismiss = { showPendingTools = false },
            )
        }
    }

    if (showCapture) PendingCaptureSheet(state, chromeActions, itemActions.onEdit, onDismiss = {
        showCapture = false
        chromeActions.onDismissCompletedUpload()
    })

    val reviewSheetState = PendingReviewSheetHostState(
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
        readOnly = state.readOnly,
        thumbnails = state.thumbnails,
        inputValues = state.reviewInputValues,
        inputReady = state.reviewInputReady,
        inputWriting = state.reviewInputWriting,
        inputNeedsReview = state.reviewInputNeedsReview,
        inputError = state.reviewInputError?.asString(),
        inputSaved = state.reviewTasks.any { it.expense.id == state.activeSheet.reviewExpense()?.id &&
            it.original.formKey == state.activeSheet.reviewInputKey() },
    )
    // expanded 下复核由 supporting pane 常驻承接，其余宽度维持现有 modal sheet；
    // 两种形态互斥，复用同一份 state/actions，不新造 review owner。
    // pane 形态始终安装并消费 Back：仅在退出权允许时 dismiss，在途 mutation
    // 进行中 Back 为 no-op——不得把 Back 透传给 NavHost/Activity 离开当前页、
    // 隐藏在途 mutation（与 pane 退出按钮同一裁决）。
    if (supportingContent is PendingSupportingPaneContent.Review) {
        val paneExit = pendingPaneExit(
            sheet = state.activeSheet,
            actionInProgressIds = state.actionInProgressIds,
            bulkRunning = state.bulkConfirm.running,
        )
        BackHandler {
            if (paneExit.enabled) sheetActions.onDismiss()
        }
    } else {
        PendingReviewSheetHost(
            state = reviewSheetState,
            actions = sheetActions,
        )
    }

    AppAdaptivePaneScaffold(
        structure = AppAdaptivePaneStructures.Inbox,
        policy = adaptivePolicy,
        primaryPane = {
            AppScrollableContent(
                chrome = AppScrollableContentChrome(
                    role = AppPageRole.Pending,
                    bottomBar = onStartReview?.takeIf { supportingContent !is PendingSupportingPaneContent.Review }?.let { start -> {
                        com.ticketbox.ui.components.AppFloatingActionBar {
                            com.ticketbox.ui.components.AppPrimaryButton(
                                text = stringResource(R.string.pending_start_review),
                                modifier = Modifier.fillMaxWidth(),
                                onClick = start,
                            )
                        }
                    } },
                    layout = AppScrollableContentLayout(
                        horizontalPadding = AppSpacing.cardPaddingSmall,
                        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
                        // 600–840dp 单窗格不再把队列/空态拉满整宽：
                        // 内容居中并封顶 secondary 宽度，compact 维持全宽。
                        contentWidth = AppAdaptiveContentWidth.Secondary,
                    ),
                ),
                refresh = AppScrollableRefreshState(
                    isRefreshing = state.showPageRefresh,
                    onRefresh = chromeActions.onRefresh,
                ),
                listState = listState,
            ) {
                item(key = "pending-header") {
                    PendingTop(
                        state = PendingTopState(
                            counts = queueCounts,
                            uploading = state.uploading,
                            readOnly = readOnly,
                            showUploadAction = !readOnly,
                            canStartUpload = state.canStartUpload,
                        ),
                        onUploadScreenshot = chromeActions.onUploadScreenshot,
                        trailingAction = {
                            PendingDisplayModeButton(
                                loading = blockingRefresh,
                                onClick = { showPendingTools = true },
                            )
                        },
                    )
                }
                if (!adaptivePolicy.showsSupportingPane) {
                    item {
                        PendingTriagePane(
                            state = triagePaneState,
                            actions = triagePaneActions,
                            showRelatedActions = false,
                        )
                    }
                }

        if (state.items.isEmpty() && !readOnly) {
            item { PendingClearCelebration(visible = showCelebration) }
        }

        if (state.reviewTasks.isNotEmpty() || state.reviewInputError != null) item(key = "pending-original-inputs") {
            com.ticketbox.ui.screens.pending.PendingReviewTasks(state.reviewTasks,
                state.reviewInputError?.asString(), sheetActions.onRetryReviewInput, sheetActions.onResumeReviewInput)
        }
        state.undoableExpense?.let { undoable ->
            item(key = "undo-${undoable.id}") {
                PendingUndoRejectBanner(expense = undoable, onUndo = reviewActions.queue.onUndoReject)
            }
        }

        if (chromeActions.uploadSelection.pendingCount > 0 || state.upload.showSummary || state.uploading) {
            item {
                SettingsEntryRow(
                    title = stringResource(R.string.pending_capture_open),
                    subtitle = if (chromeActions.uploadSelection.pendingCount > 0)
                        stringResource(R.string.pending_capture_selected, chromeActions.uploadSelection.pendingCount)
                    else stringResource(R.string.pending_capture_received, state.upload.originals.count { it.expenseId != null }, state.upload.originals.size),
                    icon = R.drawable.ic_lucide_image_plus,
                    onClick = { showCapture = true },
                )
                if (state.upload.showSummary && state.upload.completed && !state.uploading &&
                    chromeActions.uploadSelection.pendingCount == 0) {
                    TextButton(onClick = chromeActions.onDismissCompletedUpload) {
                        Text(stringResource(R.string.pending_capture_dismiss_completed))
                    }
                }
            }
        }

        messageCardText
            ?.takeIf { bodyState != PendingListBodyState.LoadFailed }
            ?.let { message ->
            item { PendingMessageCard(message = message) }
        }

        if (state.enrichment.activeCount > 0 || state.enrichment.feedback != null) {
            item {
                PendingEnrichmentStatusBand(
                    state = state.enrichment,
                    feedbackTargetPresent = enrichmentTarget != null,
                    onOpenFeedbackExpense = { enrichmentTarget?.let(itemActions.onEdit) },
                    onRetryObservation = chromeActions.onRetryEnrichment,
                    onDismissFeedback = chromeActions.onDismissEnrichment,
                )
            }
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

            bodyState == PendingListBodyState.Empty && !state.uploading && chromeActions.uploadSelection.pendingCount == 0 -> {
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

        if (!adaptivePolicy.showsSupportingPane && state.items.isEmpty()) {
            item {
                InboxActionLinks(
                    onOpenRepaymentReview = chromeActions.onOpenRepaymentReview,
                    onOpenDataQuality = chromeActions.onOpenDataQuality,
                )
            }
        }
        if (state.items.isNotEmpty()) {
            if (filteredItems.isEmpty()) {
                item { NeedsReviewEmptyFilterCard(filter = needsReviewFilter) }
            } else {
                itemsIndexed(filteredItems, key = { _, expense -> expense.id }) { index, expense ->
                    val accountingDay = expenseAccountingDayLabel(expense)
                    if (index == 0 || accountingDay != expenseAccountingDayLabel(filteredItems[index - 1])) {
                        Text(
                            text = accountingDay?.let(::displayCalendarDay)
                                ?: stringResource(R.string.calendar_date_pending),
                            style = MaterialTheme.typography.titleLarge,
                            modifier = Modifier.padding(top = AppSpacing.smallGap),
                        )
                    }
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
                            readOnly = readOnly,
                            reviewing = expense.id == paneReviewExpenseId,
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
            PendingSupportingPaneBody(
                content = supportingContent,
                reviewState = reviewSheetState,
                reviewActions = sheetActions,
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
)

private data class PendingTriagePaneActions(
    val onSelectFilter: (NeedsReviewFilter) -> Unit,
    val onOpenRepaymentReview: () -> Unit,
    val onOpenDataQuality: () -> Unit,
    val onOpenBulkConfirm: () -> Unit,
)

@Composable
private fun PendingTriagePane(
    state: PendingTriagePaneState,
    actions: PendingTriagePaneActions,
    showRelatedActions: Boolean = true,
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
        if (state.authorityTone != DataAuthorityTone.Backend) {
            AppDataAuthorityStrip(
                tone = state.authorityTone,
                localCacheBodyRes = R.string.components_data_authority_pending_cache_body,
            )
        }
        if (state.counts.all > 0 || state.selectedFilter != NeedsReviewFilter.All) {
            NeedsReviewFilterBar(
                state = NeedsReviewFilterBarState(selected = state.selectedFilter, counts = state.counts),
                onSelect = actions.onSelectFilter,
            )
        }
        if (showRelatedActions) {
            InboxActionLinks(
                onOpenRepaymentReview = actions.onOpenRepaymentReview,
                onOpenDataQuality = actions.onOpenDataQuality,
            )
        }
    }
}

private val PendingInformationActions = setOf(
    PendingPrimaryReviewAction.MissingAmount,
    PendingPrimaryReviewAction.QuickCategory,
    PendingPrimaryReviewAction.QuickMerchant,
)
