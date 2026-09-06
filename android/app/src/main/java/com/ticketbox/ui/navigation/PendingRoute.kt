package com.ticketbox.ui.navigation

import android.net.Uri
import androidx.activity.compose.ManagedActivityResultLauncher
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.ticketbox.ui.screens.PendingScreen
import com.ticketbox.ui.screens.pending.PendingDuplicateReviewActions
import com.ticketbox.ui.screens.pending.PendingExpenseQueueActions
import com.ticketbox.ui.screens.pending.PendingQueueReviewActions
import com.ticketbox.ui.screens.pending.PendingQuickFixEntryActions
import com.ticketbox.ui.screens.pending.PendingReviewFlowActions
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostActions
import com.ticketbox.ui.screens.pending.PendingScreenChromeActions
import com.ticketbox.viewmodel.PendingViewModel
import com.ticketbox.viewmodel.closeSheet
import com.ticketbox.viewmodel.confirmReadyExpenses
import com.ticketbox.viewmodel.openBulkConfirm
import com.ticketbox.viewmodel.openDuplicateAction
import com.ticketbox.viewmodel.openMissingAmount
import com.ticketbox.viewmodel.openQuickCategory
import com.ticketbox.viewmodel.openQuickMerchant
import com.ticketbox.viewmodel.saveAmountAndConfirm
import com.ticketbox.viewmodel.saveAmountDraft
import com.ticketbox.viewmodel.saveQuickCategory
import com.ticketbox.viewmodel.saveQuickMerchant
import com.ticketbox.viewmodel.skipReviewField

@Composable
internal fun PendingRoute(
    navController: NavHostController,
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
) {
    val pendingFactory = remember(screenFactory, shellState) {
        screenFactory.repositoryViewModelFactory(shellState::markInsightsDataChanged)
    }
    val pendingViewModel: PendingViewModel = viewModel(factory = pendingFactory)
    // Narrow hook (218-B4 review): only actions that LAND in confirmed
    // expenses (confirm paths) invalidate the advice cache — uploads and
    // pending-side lifecycle leave the advisor inputs unchanged.
    LaunchedEffect(pendingViewModel) {
        pendingViewModel.onAdviceInputsChanged = {
            screenFactory.budgetRepository.invalidateBudgetAdvice()
        }
    }
    val state by pendingViewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val uploadSource = remember(context.applicationContext) { pendingUploadSource(context) }

    // Targeted entries (data-quality remediation) land on the PRESERVED
    // PendingViewModel with only a client-side filter — unlike Transactions
    // (applyDataQualityFilter syncs). Re-sync so the filtered list can't be
    // stale when the data changed off-page (PR #230 round 9).
    LaunchedEffect(shellState.pendingFilterRequest.pending) {
        if (shellState.pendingFilterRequest.pending != null) {
            pendingViewModel.refresh()
        }
    }

    LaunchedEffect(shellState.expenseEditCompletionRevision) {
        if (shellState.expenseEditCompletionRevision > 0) {
            pendingViewModel.refresh()
        }
    }

    val imagePickerLauncher = rememberSingleImageUploadLauncher(shellState)
    val launchImagePicker: () -> Boolean = {
        if (state.canStartUpload) {
            imagePickerLauncher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
            true
        } else {
            false
        }
    }

    // 待确认页负责的两个入口动作：「传小票」shortcut 拉起图片选择 / 系统分享图直传。
    PendingLaunchActionEffect(
        shellState = shellState,
        canAcceptUpload = state.canStartUpload,
        onOpenPicker = launchImagePicker,
        onUploadSharedImages = { uris -> pendingViewModel.acceptUploads(uris, uploadSource) },
    )

    PendingScreen(
        state = state,
        chromeActions = pendingScreenChromeActions(
            viewModel = pendingViewModel,
            onUploadScreenshot = { launchImagePicker() },
            navigation = PendingInboxNavigationActions(
                onOpenRepaymentReview = shellState::openRepaymentDrafts,
                onOpenDataQuality = {
                    shellState.openSecondaryPage(ProductSecondaryPage.InsightsDataQuality)
                },
            ),
            filterRequest = shellState.pendingFilterRequest,
        ),
        itemActions = pendingExpenseQueueActions(navController, pendingViewModel),
        reviewActions = pendingReviewFlowActions(pendingViewModel),
        sheetActions = pendingReviewSheetActions(pendingViewModel),
    )
}

internal data class PendingInboxNavigationActions(
    val onOpenRepaymentReview: () -> Unit,
    val onOpenDataQuality: () -> Unit,
)

internal fun pendingScreenChromeActions(
    viewModel: PendingViewModel,
    onUploadScreenshot: () -> Unit,
    navigation: PendingInboxNavigationActions,
    filterRequest: PendingFilterRequestState,
): PendingScreenChromeActions = PendingScreenChromeActions(
    onRefresh = viewModel::refresh,
    onUploadScreenshot = onUploadScreenshot,
    onOpenRepaymentReview = navigation.onOpenRepaymentReview,
    onOpenDataQuality = navigation.onOpenDataQuality,
    onRetryEnrichment = viewModel::retryEnrichmentObservation,
    onRetryCapacityUpload = viewModel::retryCapacityUpload,
    onDiscardCapacityUpload = viewModel::discardCapacityUpload,
    requestedFilter = filterRequest.pending,
    onRequestedFilterConsumed = { filterRequest.consume() },
)

private fun pendingExpenseQueueActions(
    navController: NavHostController,
    viewModel: PendingViewModel,
): PendingExpenseQueueActions = PendingExpenseQueueActions(
    onEdit = { navController.openExpense(it.id) },
    onConfirm = viewModel::confirm,
    onReject = viewModel::reject,
    onKeepDuplicate = viewModel::markNotDuplicate,
)

private fun pendingReviewFlowActions(viewModel: PendingViewModel): PendingReviewFlowActions =
    PendingReviewFlowActions(
        quickFix = PendingQuickFixEntryActions(
            onQuickCategory = viewModel::openQuickCategory,
            onQuickMerchant = viewModel::openQuickMerchant,
            onMissingAmount = viewModel::openMissingAmount,
        ),
        duplicate = PendingDuplicateReviewActions(
            onOpenDuplicate = viewModel::openDuplicateAction,
        ),
        queue = PendingQueueReviewActions(
            onOpenBulkConfirm = viewModel::openBulkConfirm,
            onUndoReject = viewModel::undoReject,
        ),
    )

private fun pendingReviewSheetActions(viewModel: PendingViewModel): PendingReviewSheetHostActions =
    PendingReviewSheetHostActions(
        onSaveQuickCategory = viewModel::saveQuickCategory,
        onSaveQuickMerchant = viewModel::saveQuickMerchant,
        onSaveAmountDraft = viewModel::saveAmountDraft,
        onSaveAmountAndConfirm = viewModel::saveAmountAndConfirm,
        onSkipReviewField = viewModel::skipReviewField,
        onKeepBoth = viewModel::markNotDuplicate,
        // ADR-0038 V14: distinct from reject() — same backend transition,
        // different UX. "忽略" on duplicate sheet must NOT seed the 撤销
        // banner or show "已删除".
        onIgnoreCurrent = viewModel::ignoreDuplicate,
        onConfirmReady = viewModel::confirmReadyExpenses,
        onDismiss = viewModel::closeSheet,
    )

/**
 * 列表内「上传截图」按钮 + 「传小票」shortcut 共用的单图选择器：选一张图 → IO 预处理
 * → 走在线-only 上传链。与系统分享多图路径同一套预处理 + VM 入口，只是单张、由系统
 * 图片选择触发。
 */
@Composable
internal fun rememberSingleImageUploadLauncher(
    shellState: MainShellState,
): ManagedActivityResultLauncher<PickVisualMediaRequest, Uri?> =
    rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        shellState.launchAction.post(LaunchAction.UploadSharedImages(listOf(uri.toString())))
    }

/**
 * 消费 MainShell 派发给待确认页的入口动作（W1）：「传小票」shortcut 拉起系统图片选择，
 * 或系统分享图直传。只在动作是自己负责的变体时 [LaunchActionState.consume]
 * （取走即清空），不是自己的留给对的 Route——tab 过场两 Route 短暂共存也不会被错的一方吞掉。
 */
@Composable
internal fun PendingLaunchActionEffect(
    shellState: MainShellState,
    canAcceptUpload: Boolean,
    onOpenPicker: () -> Boolean,
    onUploadSharedImages: (List<String>) -> Boolean,
) {
    // rememberUpdatedState 让 effect 始终读到最新回调，不因首帧捕获而失效。
    val currentOpenPicker by rememberUpdatedState(onOpenPicker)
    val currentUploadShared by rememberUpdatedState(onUploadSharedImages)
    LaunchedEffect(shellState.launchAction.pending, canAcceptUpload) {
        when (val action = shellState.launchAction.pending) {
            is LaunchAction.OpenImagePicker -> {
                if (canAcceptUpload && currentOpenPicker()) shellState.launchAction.consume(action)
            }
            is LaunchAction.UploadSharedImages -> {
                if (currentUploadShared(action.uris)) shellState.launchAction.consume(action)
            }
            else -> Unit
        }
    }
}
