package com.ticketbox.ui.navigation

import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.res.stringResource
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewmodel.compose.viewModel
import androidx.navigation.NavHostController
import com.ticketbox.R
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.ui.screens.LedgerScreen
import com.ticketbox.viewmodel.LedgerViewModel

@Composable
internal fun LedgerRoute(
    navController: NavHostController,
    shellState: MainShellState,
    screenFactory: MainScreenFactory,
) {
    val ledgerViewModel: LedgerViewModel = viewModel(factory = screenFactory.repositoryViewModelFactory)
    val state by ledgerViewModel.uiState.collectAsStateWithLifecycle()
    val context = LocalContext.current
    var pendingExport by remember { mutableStateOf<CsvExport?>(null) }
    // ADR-0044: stringResource is @Composable-only; hoist the post-save export copy
    // here so the (non-composable) launcher-result callbacks pass already-resolved
    // text into exportFinished (which carries it as UiText.Raw).
    val exportCancelledMessage = stringResource(R.string.ledger_msg_export_cancelled)
    val exportSucceededMessage = stringResource(R.string.ledger_msg_export_succeeded)
    val exportFailedMessage = stringResource(R.string.ledger_msg_export_failed)

    LaunchedEffect(shellState.expenseEditCompletionRevision) {
        if (shellState.expenseEditCompletionRevision > 0) {
            ledgerViewModel.sync()
        }
    }

    val exportLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.CreateDocument("text/csv"),
    ) { uri ->
        val exportFile = pendingExport
        pendingExport = null
        if (uri == null || exportFile == null) {
            ledgerViewModel.exportFinished(exportCancelledMessage)
            return@rememberLauncherForActivityResult
        }
        runCatching {
            context.contentResolver.openOutputStream(uri)?.use { output ->
                output.write(exportFile.bytes)
            } ?: error("Output stream is null")
        }
            .onSuccess { ledgerViewModel.exportFinished(exportSucceededMessage) }
            .onFailure { ledgerViewModel.exportFinished(exportFailedMessage) }
    }

    LaunchedEffect(state.exportFile) {
        val exportFile = state.exportFile ?: return@LaunchedEffect
        pendingExport = exportFile
        exportLauncher.launch(exportFile.fileName)
        ledgerViewModel.exportLaunchHandled()
    }

    LedgerScreen(
        state = state,
        onMonthChange = ledgerViewModel::setMonthFilter,
        onCategoryChange = ledgerViewModel::setCategoryFilter,
        onTagChange = ledgerViewModel::setTagFilter,
        onQueryChange = ledgerViewModel::setQuery,
        onClearFilters = ledgerViewModel::clearFilters,
        onSync = ledgerViewModel::sync,
        onExportCsv = ledgerViewModel::exportCsv,
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
    )
}
