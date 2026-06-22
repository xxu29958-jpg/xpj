package com.ticketbox.ui.navigation

import android.content.Context
import android.net.Uri
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
    // ADR-0044: stringResource 是 @Composable-only,导出回调要的文案在此提升为已解析文本。
    val exportCancelledMessage = stringResource(R.string.ledger_msg_export_cancelled)
    val exportSucceededMessage = stringResource(R.string.ledger_msg_export_succeeded)
    val exportFailedMessage = stringResource(R.string.ledger_msg_export_failed)

    SyncLedgerAfterExpenseEdit(shellState, ledgerViewModel)
    ApplyPendingLedgerDrill(shellState, ledgerViewModel)

    val exportLauncher = rememberLauncherForActivityResult(
        contract = ActivityResultContracts.CreateDocument("text/csv"),
    ) { uri ->
        val exportFile = pendingExport
        pendingExport = null
        if (uri == null || exportFile == null) {
            ledgerViewModel.exportFinished(exportCancelledMessage)
            return@rememberLauncherForActivityResult
        }
        writeCsvExport(context, uri, exportFile) { ok ->
            ledgerViewModel.exportFinished(if (ok) exportSucceededMessage else exportFailedMessage)
        }
    }

    LaunchedEffect(state.exportFile) {
        val exportFile = state.exportFile ?: return@LaunchedEffect
        pendingExport = exportFile
        exportLauncher.launch(exportFile.fileName)
        ledgerViewModel.exportLaunchHandled()
    }

    LedgerScreen(
        state = state,
        // 「记一笔」shortcut 一次性动作:只消费属于自己的 OpenManualEntry 变体。
        openManualEntryRequested = shellState.launchAction.pending is LaunchAction.OpenManualEntry,
        onManualEntryConsumed = {
            if (shellState.launchAction.pending is LaunchAction.OpenManualEntry) shellState.launchAction.consume()
        },
        onMonthChange = ledgerViewModel::setMonthFilter,
        onCategoryChange = ledgerViewModel::setCategoryFilter,
        onTagChange = ledgerViewModel::setTagFilter,
        onQueryChange = ledgerViewModel::setQuery,
        onClearFilters = ledgerViewModel::clearFilters,
        onSync = ledgerViewModel::sync,
        onExportCsv = ledgerViewModel::exportCsv,
        onOpenBillSplit = { shellState.openStatsSecondary(StatsSecondaryPage.BillSplits) },
        onManualCreate = ledgerViewModel::createManualExpense,
        onViewModeChange = ledgerViewModel::setViewMode,
        // issue #65 slice 4: a not-yet-synced offline create has a negative local
        // id the server can't resolve, and the detail screen loads by server id —
        // so it isn't tappable into edit until it syncs. Slice 5 gives pending
        // rows their own visible affordance + local-backed editing.
        onEdit = { if (it.id > 0) navController.openExpense(it.id) },
        onEnterSelection = ledgerViewModel::enterSelection,
        onExitSelection = ledgerViewModel::exitSelection,
        onToggleSelect = ledgerViewModel::toggleSelected,
        onSelectAllVisible = ledgerViewModel::selectAllVisible,
        onApplyBatchCategory = ledgerViewModel::applyBatchCategory,
        onApplyBatchTags = ledgerViewModel::applyBatchTags,
        onManualCreateSettled = ledgerViewModel::manualCreateSettled,
        onBatchSettled = ledgerViewModel::batchSettled,
    )
}

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
private fun ApplyPendingLedgerDrill(
    shellState: MainShellState,
    ledgerViewModel: LedgerViewModel,
) {
    // §三报表钻取:消费统计页 post 的一次性(月, 分类)请求(取走即清,
    // tab 过场重组不会重复覆盖用户随后手改的筛选)。
    LaunchedEffect(shellState.ledgerDrill.pending) {
        shellState.ledgerDrill.consume()?.let { request ->
            ledgerViewModel.applyDrillFilter(month = request.month, category = request.category)
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
