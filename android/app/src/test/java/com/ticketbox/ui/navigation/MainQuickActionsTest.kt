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
                ShortcutTarget.CaptureReceipt,
                ShortcutTarget.UploadReceipt,
                ShortcutTarget.ManualEntry,
                ShortcutTarget.EntryTemplates,
                ShortcutTarget.ReviewPending,
            ),
            quickActionTargets(canModify = true),
        )
    }

    @Test fun widgetCameraTemplatesAndSyncFiltersSurviveTheGateHandoff() {
        val targets = mapOf(
            ShortcutTarget.CaptureReceipt to LaunchAction.OpenCamera,
            ShortcutTarget.EntryTemplates to LaunchAction.OpenTemplates,
            ShortcutTarget.PendingUploads to LaunchAction.OpenSyncStatus(com.ticketbox.domain.model.SyncQueueFilter.Uploads),
            ShortcutTarget.PendingRecords to LaunchAction.OpenSyncStatus(com.ticketbox.domain.model.SyncQueueFilter.Records),
            ShortcutTarget.FailedOperations to LaunchAction.OpenSyncStatus(com.ticketbox.domain.model.SyncQueueFilter.Failed),
        )
        targets.forEach { (target, expected) ->
            val state = MainShellState()
            dispatchShortcutNavigation(target, state)
            assertEquals(expected, LaunchActionState.restore(state.launchAction.snapshot()).consume())
        }
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
