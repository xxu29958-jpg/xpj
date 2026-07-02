package com.ticketbox.ui.screens

import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.ui.res.stringResource
import com.ticketbox.R
import com.ticketbox.ui.asString
import com.ticketbox.ui.components.MonthPickerSheet
import com.ticketbox.ui.screens.ledger.LedgerBulkEditSheet
import com.ticketbox.ui.screens.ledger.LedgerToolsSheet
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
            onSelectMonth = { month ->
                actions.onMonthChange(month)
                chromeState.showMonthPicker = false
            },
        )
    }
}

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
        ManualExpenseSheet(
            categories = state.categories,
            saving = state.creatingManual,
            recentMerchants = state.recentMerchants,
            errorMessage = state.manualCreateError?.asString(),
            onCreate = actions.onManualCreate,
            onDismiss = dismissManualSheet,
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
    ModalBottomSheet(onDismissRequest = { chromeState.showLedgerTools = false }) {
        val openSecondaryPage: (() -> Unit) -> Unit = { open ->
            chromeState.showLedgerTools = false
            open()
        }
        LedgerToolsSheet(
            state = state,
            canExport = canExport,
            onCategoryChange = actions.onCategoryChange,
            onTagChange = actions.onTagChange,
            onQueryChange = actions.onQueryChange,
            onClearFilters = actions.onClearFilters,
            onViewModeChange = actions.onViewModeChange,
            onSync = actions.onSync,
            onExportCsv = actions.onExportCsv,
            onOpenBillSplit = { openSecondaryPage(actions.onOpenBillSplit) },
            onOpenDebts = { openSecondaryPage(actions.onOpenDebts) },
            onOpenReceivables = { openSecondaryPage(actions.onOpenReceivables) },
            onOpenRepaymentDrafts = { openSecondaryPage(actions.onOpenRepaymentDrafts) },
            onOpenGlobalSearch = { openSecondaryPage(actions.onOpenGlobalSearch) },
            onDismiss = { chromeState.showLedgerTools = false },
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
            selectedCount = state.selectedCount,
            selectedHaveTags = state.selectedHaveTags,
            categories = state.categories,
            applying = state.applyingBatch,
            onApplyCategory = actions.onApplyBatchCategory,
            onApplyTags = actions.onApplyBatchTags,
        )
    }
}
