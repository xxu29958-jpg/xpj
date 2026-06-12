package com.ticketbox.ui.navigation

import android.content.Context
import android.net.Uri
import androidx.activity.compose.ManagedActivityResultLauncher
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.rememberUpdatedState
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.ticketbox.ui.screens.PendingScreen
import com.ticketbox.upload.prepareScreenshotUpload
import com.ticketbox.viewmodel.PendingViewModel
import kotlinx.coroutines.CoroutineScope
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
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext

@Composable
internal fun PendingRoute(
    navController: NavHostController,
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
) {
    val pendingViewModel: PendingViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val state by pendingViewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    val uploadScope = rememberCoroutineScope()

    LaunchedEffect(shellState.expenseEditCompletionRevision) {
        if (shellState.expenseEditCompletionRevision > 0) {
            pendingViewModel.refresh()
        }
    }

    val imagePickerLauncher = rememberSingleImageUploadLauncher(pendingViewModel, context, uploadScope)
    val launchImagePicker = {
        imagePickerLauncher.launch(PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly))
    }

    // 待确认页负责的两个入口动作：「传小票」shortcut 拉起图片选择 / 系统分享图直传。
    PendingLaunchActionEffect(
        shellState = shellState,
        onOpenPicker = launchImagePicker,
        onUploadSharedImages = { uris -> uploadSharedImages(context, pendingViewModel, uris) },
    )

    PendingScreen(
        state = state,
        onRefresh = pendingViewModel::refresh,
        onEdit = { navController.openExpense(it.id) },
        onConfirm = pendingViewModel::confirm,
        onReject = pendingViewModel::reject,
        onKeepDuplicate = pendingViewModel::markNotDuplicate,
        onUploadScreenshot = launchImagePicker,
        onQuickCategory = pendingViewModel::openQuickCategory,
        onSaveQuickCategory = pendingViewModel::saveQuickCategory,
        onQuickMerchant = pendingViewModel::openQuickMerchant,
        onSaveQuickMerchant = pendingViewModel::saveQuickMerchant,
        onMissingAmount = pendingViewModel::openMissingAmount,
        onSaveAmountDraft = pendingViewModel::saveAmountDraft,
        onSaveAmountAndConfirm = pendingViewModel::saveAmountAndConfirm,
        onOpenBulkConfirm = pendingViewModel::openBulkConfirm,
        onConfirmReady = pendingViewModel::confirmReadyExpenses,
        onOpenDuplicate = pendingViewModel::openDuplicateAction,
        // ADR-0038 V14: distinct from reject() — same backend transition,
        // different UX. "忽略" on duplicate sheet must NOT seed the 撤销
        // banner or show "已删除".
        onIgnoreDuplicate = pendingViewModel::ignoreDuplicate,
        onCloseSheet = pendingViewModel::closeSheet,
        onUndoReject = pendingViewModel::undoReject,
    )
}

/**
 * 列表内「上传截图」按钮 + 「传小票」shortcut 共用的单图选择器：选一张图 → IO 预处理
 * → 走在线-only 上传链。与系统分享多图路径同一套预处理 + VM 入口，只是单张、由系统
 * 图片选择触发。
 */
@Composable
private fun rememberSingleImageUploadLauncher(
    viewModel: PendingViewModel,
    context: Context,
    scope: CoroutineScope,
): ManagedActivityResultLauncher<PickVisualMediaRequest, Uri?> =
    rememberLauncherForActivityResult(ActivityResultContracts.PickVisualMedia()) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        if (!viewModel.markUploadPreparing()) return@rememberLauncherForActivityResult
        scope.launch {
            val selected = withContext(Dispatchers.IO) { context.prepareScreenshotUpload(uri) }
            if (selected == null) {
                viewModel.uploadPreparationFailed()
                return@launch
            }
            viewModel.uploadScreenshot(
                fileName = selected.fileName,
                contentType = selected.contentType,
                bytes = selected.bytes,
                preparationDurationMs = selected.preparationDurationMs,
                sourceSizeBytes = selected.sourceSizeBytes,
                uploadAlreadyStarted = true,
            )
        }
    }

/**
 * 消费 MainShell 派发给待确认页的入口动作（W1）：「传小票」shortcut 拉起系统图片选择，
 * 或系统分享图直传。只在动作是自己负责的变体时 [LaunchActionState.consume]
 * （取走即清空），不是自己的留给对的 Route——tab 过场两 Route 短暂共存也不会被错的一方吞掉。
 */
@Composable
private fun PendingLaunchActionEffect(
    shellState: MainShellState,
    onOpenPicker: () -> Unit,
    onUploadSharedImages: suspend (List<String>) -> Unit,
) {
    // rememberUpdatedState 让 effect 始终读到最新回调，不因首帧捕获而失效。
    val currentOpenPicker by rememberUpdatedState(onOpenPicker)
    val currentUploadShared by rememberUpdatedState(onUploadSharedImages)
    LaunchedEffect(shellState.launchAction.pending) {
        when (shellState.launchAction.pending) {
            is LaunchAction.OpenImagePicker -> {
                shellState.launchAction.consume()
                currentOpenPicker()
            }
            is LaunchAction.UploadSharedImages -> {
                val action = shellState.launchAction.consume() as? LaunchAction.UploadSharedImages
                if (action != null) currentUploadShared(action.uris)
            }
            else -> Unit
        }
    }
}

/**
 * 顺序上传系统分享带进来的图片。每张：抢 in-progress 锁（[PendingViewModel.markUploadPreparing]，
 * 同时快照 ledger/generation）→ IO 线程预处理 → await 上传完成 → 再下一张。
 *
 * 第一张若拿不到锁（已有上传在跑）即整体放弃；中途某张预处理失败标记「读不出」并跳过，
 * 不中断其余张。账本切换 / 旧请求作废由 VM 内部守卫处理（会把当前张丢弃并提示）。
 */
private suspend fun uploadSharedImages(
    context: Context,
    viewModel: PendingViewModel,
    uris: List<String>,
) {
    for (rawUri in uris) {
        if (!viewModel.markUploadPreparing()) return
        val uri = runCatching { Uri.parse(rawUri) }.getOrNull()
        val prepared = uri?.let {
            withContext(Dispatchers.IO) { context.prepareScreenshotUpload(it) }
        }
        if (prepared == null) {
            viewModel.uploadPreparationFailed()
            continue
        }
        viewModel.uploadPreparedImage(prepared)
    }
}
