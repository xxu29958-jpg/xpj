package com.ticketbox.ui.screens.ledger

import kotlin.test.Test
import kotlin.test.assertEquals

class LedgerStatusTextTest {
    @Test
    fun syncEvidenceIsRefreshingWhileRequestIsInFlight() {
        assertEquals(
            LedgerSyncEvidence.Refreshing,
            ledgerSyncEvidence(syncing = true, syncedInCurrentSession = false),
        )
        assertEquals(
            LedgerSyncEvidence.Refreshing,
            ledgerSyncEvidence(syncing = true, syncedInCurrentSession = true),
        )
    }

    @Test
    fun syncEvidenceRequiresCurrentSessionSuccessForBackendCopy() {
        assertEquals(
            LedgerSyncEvidence.BackendSynced,
            ledgerSyncEvidence(syncing = false, syncedInCurrentSession = true),
        )
        assertEquals(
            LedgerSyncEvidence.LocalCache,
            ledgerSyncEvidence(syncing = false, syncedInCurrentSession = false),
        )
    }
}
