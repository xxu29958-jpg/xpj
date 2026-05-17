package com.ticketbox.ui.navigation

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.PickVisualMediaRequest
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.ticketbox.ui.screens.PendingScreen
import com.ticketbox.upload.prepareScreenshotUpload
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

    val imagePickerLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.PickVisualMedia(),
    ) { uri ->
        if (uri == null) return@rememberLauncherForActivityResult
        if (!pendingViewModel.markUploadPreparing()) return@rememberLauncherForActivityResult
        uploadScope.launch {
            val selected = withContext(Dispatchers.IO) {
                context.prepareScreenshotUpload(uri)
            }
            if (selected == null) {
                pendingViewModel.uploadPreparationFailed()
                return@launch
            }
            pendingViewModel.uploadScreenshot(
                fileName = selected.fileName,
                contentType = selected.contentType,
                bytes = selected.bytes,
                preparationDurationMs = selected.preparationDurationMs,
                sourceSizeBytes = selected.sourceSizeBytes,
                uploadAlreadyStarted = true,
            )
        }
    }

    PendingScreen(
        state = state,
        onRefresh = pendingViewModel::refresh,
        onEdit = { navController.openExpense(it.id) },
        onConfirm = pendingViewModel::confirm,
        onReject = pendingViewModel::reject,
        onKeepDuplicate = pendingViewModel::markNotDuplicate,
        onUploadScreenshot = {
            imagePickerLauncher.launch(
                PickVisualMediaRequest(ActivityResultContracts.PickVisualMedia.ImageOnly),
            )
        },
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
        onIgnoreDuplicate = pendingViewModel::reject,
        onCloseSheet = pendingViewModel::closeSheet,
    )
}
