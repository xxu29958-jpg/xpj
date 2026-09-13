package com.ticketbox.ui.screens

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.MonthPickerListState
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.components.AppSheetScaffold
import com.ticketbox.ui.screens.ledger.LedgerBulkEditSheetActions
import com.ticketbox.ui.screens.ledger.LedgerBulkEditSheetState
import com.ticketbox.ui.screens.ledger.LedgerBulkEditSheet
import com.ticketbox.ui.screens.ledger.LedgerToolsSheet
import com.ticketbox.ui.screens.ledger.LedgerToolsSheetActions
import com.ticketbox.ui.screens.ledger.LedgerToolsSheetState
import com.ticketbox.viewmodel.LedgerMonthsLoadState
import com.ticketbox.viewmodel.LedgerUiState

@OptIn(ExperimentalMaterial3Api::class)
@Composable
internal fun LedgerSheets(
    state: LedgerUiState,
    chromeState: LedgerScreenChromeState,
    actions: LedgerScreenActions,
    canExport: Boolean,
) {
    LedgerMonthPickerHost(state = state, chromeState = chromeState, actions = actions)
    LedgerManualSheetHost(state = state, chromeState = chromeState, actions = actions)
    LedgerToolsSheetHost(
        state = state,
        chromeState = chromeState,
        actions = actions,
        canExport = canExport,
    )
    LedgerBulkEditHost(state = state, chromeState = chromeState, actions = actions)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LedgerMonthPickerHost(
    state: LedgerUiState,
    chromeState: LedgerScreenChromeState,
    actions: LedgerScreenActions,
) {
    if (!chromeState.showMonthPicker) return
    ModalBottomSheet(onDismissRequest = { chromeState.showMonthPicker = false }) {
        MonthPickerSheet(
            months = state.months,
            selectedMonth = state.monthFilter,
            description = stringResource(R.string.ledger_month_picker_description),
            listState = ledgerMonthPickerListState(state.monthsLoadState),
            onSelectMonth = { month ->
                actions.onMonthChange(month)
                chromeState.showMonthPicker = false
            },
        )
    }
}

internal fun ledgerMonthPickerListState(loadState: LedgerMonthsLoadState): MonthPickerListState = when (loadState) {
    LedgerMonthsLoadState.Unknown -> MonthPickerListState.Unknown
    LedgerMonthsLoadState.Loading -> MonthPickerListState.Loading
    LedgerMonthsLoadState.Loaded -> MonthPickerListState.Loaded
    LedgerMonthsLoadState.Failed -> MonthPickerListState.Failed
}

// The CSV export endpoint only scopes by month/category/tag — the data-quality
// filter is client-side, so exporting under it would silently dump the
// unfiltered scope. Disable the affordance instead of mis-scoping the file.
internal fun ledgerExportAvailable(state: LedgerUiState): Boolean =
    state.items.isNotEmpty() && !state.exporting && state.exportFile == null && state.dataQualityFilter == null

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LedgerManualSheetHost(
    state: LedgerUiState,
    chromeState: LedgerScreenChromeState,
    actions: LedgerScreenActions,
) {
    if (!chromeState.showManualSheet || state.readOnly) return
    val dismissManualSheet = {
        chromeState.showManualSheet = false
        actions.onManualCreateSettled()
    }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = dismissManualSheet, sheetState = sheetState) {
        PreparedManualExpenseSheet(state, actions, dismissManualSheet)
    }
}

@Composable
private fun PreparedManualExpenseSheet(state: LedgerUiState, actions: LedgerScreenActions, onDismiss: () -> Unit) {
    var currency by rememberSaveable { mutableStateOf<CurrencyCode?>(null) }
    var loading by remember { mutableStateOf(true) }
    var attempt by remember { mutableIntStateOf(0) }
    LaunchedEffect(attempt) {
        if (currency != null) { loading = false; return@LaunchedEffect }
        loading = true
        currency = actions.onPrepareManualCreate()
        loading = false
    }
    val captured = currency
    if (captured == null) {
        AppSheetScaffold(title = stringResource(R.string.ledger_manual_sheet_title)) {
            if (loading) {
                CircularProgressIndicator()
                Text(stringResource(R.string.ledger_manual_currency_loading))
            } else {
                Text(stringResource(R.string.currency_unconfirmed_write_blocked))
                TextButton(onClick = { attempt++ }) { Text(stringResource(R.string.common_retry)) }
            }
        }
    } else {
        ManualExpenseSheet(
            state = ManualExpenseSheetState(
                categories = state.categories,
                saving = state.creatingManual,
                recentMerchants = state.recentMerchants,
                initialCurrency = captured,
                errorMessage = state.manualCreateError?.asString(),
            ),
            actions = ManualExpenseSheetActions(
                onCreate = actions.onManualCreate,
                onDismiss = onDismiss,
            ),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LedgerToolsSheetHost(
    state: LedgerUiState,
    chromeState: LedgerScreenChromeState,
    actions: LedgerScreenActions,
    canExport: Boolean,
) {
    if (!chromeState.showLedgerTools) return
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = { chromeState.showLedgerTools = false }, sheetState = sheetState) {
        val openSecondaryPage: (() -> Unit) -> Unit = { open ->
            chromeState.showLedgerTools = false
            open()
        }
        LedgerToolsSheet(
            state = LedgerToolsSheetState(
                ledger = state,
                canExport = canExport,
            ),
            actions = LedgerToolsSheetActions(
                onCategoryChange = actions.onCategoryChange,
                onTagChange = actions.onTagChange,
                onQueryChange = actions.onQueryChange,
                onClearFilters = actions.onClearFilters,
                onViewModeChange = actions.onViewModeChange,
                onSync = actions.onSync,
                onExportCsv = actions.onExportCsv,
                onOpenLibrary = { openSecondaryPage(actions.onOpenLibrary) },
                onDismiss = { chromeState.showLedgerTools = false },
            ),
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LedgerBulkEditHost(
    state: LedgerUiState,
    chromeState: LedgerScreenChromeState,
    actions: LedgerScreenActions,
) {
    if (!chromeState.showBulkEdit || !state.selectionMode || state.readOnly) return
    ModalBottomSheet(onDismissRequest = { chromeState.showBulkEdit = false }) {
        LedgerBulkEditSheet(
            state = LedgerBulkEditSheetState(
                selectedCount = state.selectedCount,
                selectedHaveTags = state.selectedHaveTags,
                categories = state.categories,
                applying = state.applyingBatch,
            ),
            actions = LedgerBulkEditSheetActions(
                // A1: reason 随动作贯通到 backend 原子批量更正（Codex 接缝：
                // LedgerScreenActions 的这两个字段类型随之变为 (String, String)）。
                onApplyCategory = { category, reason -> actions.onApplyBatchCategory(category, reason) },
                onApplyTags = { tags, reason -> actions.onApplyBatchTags(tags, reason) },
            ),
        )
    }
}
