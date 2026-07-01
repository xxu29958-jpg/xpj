package com.ticketbox.ui.screens

import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.saveable.listSaver
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.viewmodel.LedgerUiState
import com.ticketbox.viewmodel.LedgerViewMode

internal data class LedgerLaunchRequest(
    val openManualEntryRequested: Boolean = false,
    val onManualEntryConsumed: () -> Unit = {},
)

internal data class LedgerScreenActions(
    val onMonthChange: (String) -> Unit = {},
    val onCategoryChange: (String) -> Unit = {},
    val onTagChange: (String) -> Unit = {},
    val onQueryChange: (String) -> Unit = {},
    val onClearFilters: () -> Unit = {},
    val onSync: () -> Unit = {},
    val onExportCsv: () -> Unit = {},
    val onOpenBillSplit: () -> Unit = {},
    val onOpenDebts: () -> Unit = {},
    val onOpenReceivables: () -> Unit = {},
    val onOpenRepaymentDrafts: () -> Unit = {},
    val onOpenGlobalSearch: () -> Unit = {},
    val onManualCreate: (ExpenseDraft) -> Unit = {},
    val onViewModeChange: (LedgerViewMode) -> Unit = {},
    val onEdit: (Expense) -> Unit = {},
    val onEnterSelection: (Long?) -> Unit = {},
    val onExitSelection: () -> Unit = {},
    val onToggleSelect: (Long) -> Unit = {},
    val onSelectAllVisible: () -> Unit = {},
    val onApplyBatchCategory: (String) -> Unit = {},
    val onApplyBatchTags: (String) -> Unit = {},
    val onManualCreateSettled: () -> Unit = {},
    val onBatchSettled: () -> Unit = {},
)

@Composable
internal fun LedgerScreen(
    state: LedgerUiState,
    launchRequest: LedgerLaunchRequest = LedgerLaunchRequest(),
    actions: LedgerScreenActions,
) {
    val chromeState = rememberLedgerScreenChromeState()
    val canExport = state.items.isNotEmpty() && !state.exporting

    LedgerScreenEffects(
        state = state,
        launchRequest = launchRequest,
        actions = actions,
        chromeState = chromeState,
    )
    LedgerSheets(
        state = state,
        chromeState = chromeState,
        actions = actions,
        canExport = canExport,
    )
    LedgerContent(state = state, actions = actions, chromeState = chromeState)
}

internal class LedgerScreenChromeState(
    showMonthPicker: Boolean = false,
    showManualSheet: Boolean = false,
    showLedgerTools: Boolean = false,
    showBulkEdit: Boolean = false,
) {
    var showMonthPicker by mutableStateOf(showMonthPicker)
    var showManualSheet by mutableStateOf(showManualSheet)
    var showLedgerTools by mutableStateOf(showLedgerTools)
    var showBulkEdit by mutableStateOf(showBulkEdit)
}

@Composable
private fun rememberLedgerScreenChromeState(): LedgerScreenChromeState {
    return rememberSaveable(saver = LedgerScreenChromeStateSaver) { LedgerScreenChromeState() }
}

@Composable
private fun LedgerScreenEffects(
    state: LedgerUiState,
    launchRequest: LedgerLaunchRequest,
    actions: LedgerScreenActions,
    chromeState: LedgerScreenChromeState,
) {
    LaunchedEffect(state.manualCreateDone) {
        if (state.manualCreateDone) {
            chromeState.showManualSheet = false
            actions.onManualCreateSettled()
        }
    }
    LaunchedEffect(state.batchDone) {
        if (state.batchDone) {
            chromeState.showBulkEdit = false
            actions.onBatchSettled()
        }
    }
    LaunchedEffect(launchRequest.openManualEntryRequested) {
        if (launchRequest.openManualEntryRequested) {
            launchRequest.onManualEntryConsumed()
            if (!state.readOnly) chromeState.showManualSheet = true
        }
    }
}

private val LedgerScreenChromeStateSaver = listSaver<LedgerScreenChromeState, Boolean>(
    save = {
        listOf(
            it.showMonthPicker,
            it.showManualSheet,
            it.showLedgerTools,
            it.showBulkEdit,
        )
    },
    restore = {
        LedgerScreenChromeState(
            showMonthPicker = it[0],
            showManualSheet = it[1],
            showLedgerTools = it[2],
            showBulkEdit = it[3],
        )
    },
)
