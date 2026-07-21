package com.ticketbox.ui.screens

import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.runtime.Composable
import com.ticketbox.R
import com.ticketbox.ui.components.AppAdaptiveSupportingPane
import com.ticketbox.ui.components.AppDataAuthorityStrip
import com.ticketbox.ui.components.AppPageRole
import com.ticketbox.ui.components.DataAuthorityTone
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.ledger.LedgerFilterPanel
import com.ticketbox.ui.screens.ledger.LedgerFilterPanelActions
import com.ticketbox.ui.screens.ledger.LedgerInlineStatusMessage
import com.ticketbox.ui.screens.ledger.LedgerSelectionBar
import com.ticketbox.viewmodel.LedgerUiState

@Composable
internal fun LedgerSupportingPane(
    state: LedgerUiState,
    actions: LedgerScreenActions,
    chromeState: LedgerScreenChromeState,
) {
    val authorityTone = ledgerAuthorityTone(state)
    AppAdaptiveSupportingPane(
        role = AppPageRole.Ledger,
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        LedgerTopChrome(
            state = state,
            actions = actions,
            chromeState = chromeState,
            showSummaryHeader = false,
        )
        if (ledgerStatusVisible(state, authorityTone)) {
            LedgerStatusContent(state = state, authorityTone = authorityTone)
        }
    }
}

@Composable
internal fun LedgerTopChrome(
    state: LedgerUiState,
    actions: LedgerScreenActions,
    chromeState: LedgerScreenChromeState,
    showSummaryHeader: Boolean,
) {
    if (state.selectionMode) {
        LedgerSelectionBar(
            selectedCount = state.selectedCount,
            applying = state.applyingBatch,
            onExit = actions.onExitSelection,
            onSelectAll = actions.onSelectAllVisible,
            onEdit = { chromeState.showBulkEdit = true },
        )
    } else {
        LedgerFilterPanel(
            state = state,
            actions = LedgerFilterPanelActions(
                onOpenMonthPicker = { chromeState.showMonthPicker = true },
                onOpenTools = { chromeState.showLedgerTools = true },
                onManualAdd = { if (!state.readOnly) chromeState.showManualSheet = true },
                onMonthChange = actions.onMonthChange,
            ),
            showSummaryHeader = showSummaryHeader,
        )
    }
}

@Composable
internal fun LedgerStatusContent(
    state: LedgerUiState,
    authorityTone: DataAuthorityTone,
) {
    Column(
        verticalArrangement = Arrangement.spacedBy(AppSpacing.smallGap),
    ) {
        if (authorityTone != DataAuthorityTone.Backend) {
            AppDataAuthorityStrip(
                tone = authorityTone,
                localCacheBodyRes = R.string.components_data_authority_ledger_cache_body,
            )
        }
        state.message?.let { message ->
            LedgerInlineStatusMessage(message = message, tone = state.messageTone)
        }
    }
}

internal fun ledgerStatusVisible(
    state: LedgerUiState,
    authorityTone: DataAuthorityTone,
): Boolean = authorityTone != DataAuthorityTone.Backend || state.message != null

internal fun ledgerAuthorityTone(state: LedgerUiState): DataAuthorityTone = when {
    state.readOnly -> DataAuthorityTone.ReadOnly
    state.showPageRefresh -> DataAuthorityTone.Refreshing
    state.syncedInCurrentSession -> DataAuthorityTone.Backend
    else -> DataAuthorityTone.LocalCache
}
