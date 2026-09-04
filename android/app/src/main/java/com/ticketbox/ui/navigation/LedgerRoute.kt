package com.ticketbox.ui.navigation

import android.content.ActivityNotFoundException
import android.content.Context
import android.net.Uri
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.remember
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.ui.screens.LedgerLaunchRequest
import com.ticketbox.ui.screens.LedgerScreen
import com.ticketbox.ui.screens.LedgerScreenActions
import com.ticketbox.viewmodel.LedgerExportOutcome
import com.ticketbox.viewmodel.LedgerViewModel

@Composable
internal fun LedgerRoute(
    navController: NavHostController,
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
) {
    val ledgerFactory = remember(screenFactory, shellState) {
        screenFactory.repositoryViewModelFactory(shellState::markInsightsDataChanged)
    }
    val ledgerViewModel: LedgerViewModel = viewModel(factory = ledgerFactory)
    // Narrow hook (218-B4 review P2-23): manual creates and category batch
    // edits invalidate the advice cache; tag-only batches preserve it.
    LaunchedEffect(ledgerViewModel) {
        ledgerViewModel.onAdviceInputsChanged = {
            screenFactory.budgetRepository.invalidateBudgetAdvice()
        }
    }
    val state by ledgerViewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current

    SyncLedgerAfterExpenseEdit(shellState, ledgerViewModel)
    SyncLedgerVocabulary(shellState, ledgerViewModel)
    ApplyPendingLedgerDrill(shellState, ledgerViewModel)

    val exportLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.CreateDocument("text/csv"),
    ) { uri ->
        val exportFile = ledgerViewModel.uiState.value.exportFile
        if (uri == null) {
            ledgerViewModel.exportFinished(LedgerExportOutcome.Cancelled)
            return@rememberLauncherForActivityResult
        }
        if (exportFile == null) {
            ledgerViewModel.exportFinished(LedgerExportOutcome.Failed)
            return@rememberLauncherForActivityResult
        }
        writeCsvExport(context, uri, exportFile) { ok ->
            ledgerViewModel.exportFinished(if (ok) LedgerExportOutcome.Saved else LedgerExportOutcome.Failed)
        }
    }

    LaunchedEffect(state.exportFile) {
        val exportFile = state.exportFile ?: return@LaunchedEffect
        if (state.exportDestinationPending) return@LaunchedEffect
        ledgerViewModel.exportLaunchHandled()
        try {
            exportLauncher.launch(exportFile.fileName)
        } catch (_: ActivityNotFoundException) {
            ledgerViewModel.exportFinished(LedgerExportOutcome.Failed)
        }
    }

    LedgerScreen(
        state = state,
        launchRequest = LedgerLaunchRequest(
            openManualEntryRequested = shellState.launchAction.pending is LaunchAction.OpenManualEntry,
            onManualEntryConsumed = {
                if (shellState.launchAction.pending is LaunchAction.OpenManualEntry) shellState.launchAction.consume()
            },
        ),
        actions = ledgerScreenActions(ledgerViewModel, navController, shellState),
    )
}

private fun ledgerScreenActions(
    ledgerViewModel: LedgerViewModel,
    navController: NavHostController,
    shellState: MainShellState,
): LedgerScreenActions = LedgerScreenActions(
    onMonthChange = ledgerViewModel::setMonthFilter,
    onCategoryChange = ledgerViewModel::setCategoryFilter,
    onTagChange = ledgerViewModel::setTagFilter,
    onQueryChange = ledgerViewModel::setQuery,
    onClearFilters = ledgerViewModel::clearFilters,
    onSync = ledgerViewModel::sync,
    onExportCsv = ledgerViewModel::exportCsv,
    onOpenGlobalSearch = { shellState.openSecondaryPage(ProductSecondaryPage.GlobalSearch) },
    onOpenLibrary = {
        shellState.openSecondaryPage(ProductSecondaryPage.TransactionsLibrary)
    },
    onManualCreate = ledgerViewModel::createManualExpense,
    onViewModeChange = ledgerViewModel::setViewMode,
    onEdit = { navController.openExpense(it.id) },
    onEnterSelection = ledgerViewModel::enterSelection,
    onExitSelection = ledgerViewModel::exitSelection,
    onToggleSelect = ledgerViewModel::toggleSelected,
    onSelectAllVisible = ledgerViewModel::selectAllVisible,
    onApplyBatchCategory = ledgerViewModel::applyBatchCategory,
    onApplyBatchTags = ledgerViewModel::applyBatchTags,
    onManualCreateSettled = ledgerViewModel::manualCreateSettled,
    onBatchSettled = ledgerViewModel::batchSettled,
)

@Composable
private fun SyncLedgerAfterExpenseEdit(
    shellState: MainShellState,
    ledgerViewModel: LedgerViewModel,
) {
    LaunchedEffect(shellState.expenseEditCompletionRevision) {
        if (shellState.expenseEditCompletionRevision > 0) {
            ledgerViewModel.sync()
        }
    }
}

@Composable
private fun SyncLedgerVocabulary(
    shellState: MainShellState,
    ledgerViewModel: LedgerViewModel,
) {
    LaunchedEffect(shellState.transactionVocabularyRevision) {
        if (shellState.transactionVocabularyRevision > 0) {
            ledgerViewModel.refreshVocabulary()
        }
    }
}

@Composable
private fun ApplyPendingLedgerDrill(
    shellState: MainShellState,
    ledgerViewModel: LedgerViewModel,
) {
    // §三报表钻取:消费统计页 post 的一次性(月, 分类)请求(取走即清,
    // tab 过场重组不会重复覆盖用户随后手改的筛选)。
    LaunchedEffect(shellState.ledgerDrill.pending) {
        when (val request = shellState.ledgerDrill.consume()) {
            is LedgerDrillRequest.Category ->
                ledgerViewModel.applyDrillFilter(month = request.month, category = request.category)
            is LedgerDrillRequest.DataQuality ->
                ledgerViewModel.applyDataQualityFilter(request.filter)
            null -> Unit
        }
    }
}

private fun writeCsvExport(
    context: Context,
    uri: Uri,
    exportFile: CsvExport,
    onResult: (Boolean) -> Unit,
) {
    runCatching {
        context.contentResolver.openOutputStream(uri)?.use { output ->
            output.write(exportFile.bytes)
        } ?: error("Output stream is null")
    }
        .onSuccess { onResult(true) }
        .onFailure { onResult(false) }
}
