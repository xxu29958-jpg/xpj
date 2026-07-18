package com.ticketbox.ui.screens

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.MonthPickerListState
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.design.LocalCurrencyCode
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

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun LedgerManualSheetHost(
    state: LedgerUiState,
    chromeState: LedgerScreenChromeState,
    actions: LedgerScreenActions,
) {
    if (!chromeState.showManualSheet || state.readOnly) return
    val homeCurrency = LocalCurrencyCode.current
    val dismissManualSheet = {
        chromeState.showManualSheet = false
        actions.onManualCreateSettled()
    }
    val sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    ModalBottomSheet(onDismissRequest = dismissManualSheet, sheetState = sheetState) {
        ManualExpenseSheet(
            state = ManualExpenseSheetState(
                categories = state.categories,
                saving = state.creatingManual,
                homeCurrency = homeCurrency,
                recentMerchants = state.recentMerchants,
                errorMessage = state.manualCreateError?.asString(),
            ),
            actions = ManualExpenseSheetActions(
                onCreate = actions.onManualCreate,
                onDismiss = dismissManualSheet,
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
                onOpenGlobalSearch = { openSecondaryPage(actions.onOpenGlobalSearch) },
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
                onApplyCategory = actions.onApplyBatchCategory,
                onApplyTags = actions.onApplyBatchTags,
            ),
        )
    }
}
