package com.ticketbox.ui.navigation

import org.junit.Assert.assertEquals
import org.junit.Test

class MainQuickActionsTest {
    @Test
    fun widgetSummaryOpensCurrentMonthAndSurvivesRestoration() {
        val state = MainShellState()
        dispatchShortcutNavigation(ShortcutTarget.MonthlyOverview, state)
        assertEquals(PrimaryDomain.Insights, state.selectedDomain)
        assertEquals(LaunchAction.OpenCurrentMonthStats, state.launchAction.pending)
        val restored = LaunchActionState.restore(state.launchAction.snapshot())
        assertEquals(LaunchAction.OpenCurrentMonthStats, restored.consume())
        assertEquals(null, restored.pending)
    }

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
