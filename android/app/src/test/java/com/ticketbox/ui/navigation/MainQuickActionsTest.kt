package com.ticketbox.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Test

class MainQuickActionsTest {
    @Test
    fun writerSeesExistingLauncherActionsInsideTheApp() {
        assertEquals(
            listOf(
                ShortcutTarget.UploadReceipt,
                ShortcutTarget.ManualEntry,
                ShortcutTarget.ReviewPending,
            ),
            quickActionTargets(canModify = true),
        )
    }

    @Test
    fun viewerOnlySeesTheReadOnlySafeReviewEntry() {
        assertEquals(
            listOf(ShortcutTarget.ReviewPending),
            quickActionTargets(canModify = false),
        )
    }

    @Test
    fun manualEntryReusesTheExistingNavigationAndLaunchActionOwners() {
        val state = MainShellState()
        state.syncDestination(MainProductDestination.Domain(PrimaryDomain.Insights))

        dispatchShortcutNavigation(ShortcutTarget.ManualEntry, state)

        assertEquals(PrimaryDomain.Transactions, state.selectedDomain)
        assertEquals(LaunchAction.OpenManualEntry, state.launchAction.pending)
        assertEquals(
            MainNavigationRequest.OpenDomain(
                domain = PrimaryDomain.Transactions,
                selectionBehavior = PrimaryDomainSelectionBehavior.OpenRoot,
            ),
            state.consumeNavigationRequest(),
        )
    }
}
