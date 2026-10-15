package com.ticketbox.ui.screens.ledger

import com.ticketbox.ui.components.displayTime
import com.ticketbox.viewmodel.LedgerUiState

internal enum class LedgerSyncEvidence {
    Refreshing,
    BackendSynced,
    LocalCache,
}

internal fun ledgerSyncClock(value: String): String {
    val label = displayTime(value)
    return label.substringAfterLast(" ").takeIf { it.isNotBlank() } ?: label
}

internal fun ledgerSyncEvidence(state: LedgerUiState): LedgerSyncEvidence =
    ledgerSyncEvidence(
        syncing = state.syncing,
        syncedInCurrentSession = state.syncedInCurrentSession,
    )

internal fun ledgerSyncEvidence(syncing: Boolean, syncedInCurrentSession: Boolean): LedgerSyncEvidence = when {
    syncing -> LedgerSyncEvidence.Refreshing
    syncedInCurrentSession -> LedgerSyncEvidence.BackendSynced
    else -> LedgerSyncEvidence.LocalCache
}
