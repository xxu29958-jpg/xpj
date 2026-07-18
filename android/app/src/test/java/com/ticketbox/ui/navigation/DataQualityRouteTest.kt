package com.ticketbox.ui.navigation

import com.ticketbox.ui.screens.pending.NeedsReviewFilter
import com.ticketbox.ui.screens.stats.DataQualityRemediation
import com.ticketbox.viewmodel.LedgerDataQualityFilter
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith

class DataQualityRouteTest {
    @Test
    fun directInboxEntryUsesCurrentOwnerWhenInsightsRootIsNotOnBackStack() {
        val owner = resolveInsightsViewModelOwner(currentEntry = "data-quality") {
            throw IllegalArgumentException("No destination with route product/insights is on the back stack")
        }

        assertEquals("data-quality", owner)
    }

    @Test
    fun ownerResolutionDoesNotHideUnexpectedFailures() {
        assertFailsWith<IllegalStateException> {
            resolveInsightsViewModelOwner(currentEntry = "data-quality") {
                throw IllegalStateException("unexpected navigation failure")
            }
        }
    }

    @Test
    fun pendingIssuePostsCorrespondingInboxFilterBeforeNavigation() {
        val shellState = MainShellState()
        shellState.syncDestination(MainProductDestination.Domain(PrimaryDomain.Insights))
        shellState.syncDestination(
            MainProductDestination.Secondary(ProductSecondaryPage.InsightsDataQuality),
        )

        openDataQualityRemediation(
            shellState,
            DataQualityRemediation.InboxMissingCategory,
        )

        assertEquals(NeedsReviewFilter.NeedsCategory, shellState.pendingFilterRequest.pending)
        assertEquals(
            MainNavigationRequest.OpenDomain(
                domain = PrimaryDomain.Inbox,
                selectionBehavior = PrimaryDomainSelectionBehavior.OpenRoot,
            ),
            shellState.consumeNavigationRequest(),
        )
    }

    @Test
    fun confirmedIssuePostsTypedTransactionsContextBeforeNavigation() {
        val shellState = MainShellState()
        shellState.syncDestination(MainProductDestination.Domain(PrimaryDomain.Insights))
        shellState.syncDestination(
            MainProductDestination.Secondary(ProductSecondaryPage.InsightsDataQuality),
        )

        openDataQualityRemediation(
            shellState,
            DataQualityRemediation.TransactionsConfirmedWithoutImage,
        )

        assertEquals(
            LedgerDrillRequest.DataQuality(LedgerDataQualityFilter.ConfirmedWithoutImage),
            shellState.ledgerDrill.pending,
        )
        assertEquals(
            MainNavigationRequest.OpenDomain(
                domain = PrimaryDomain.Transactions,
                selectionBehavior = PrimaryDomainSelectionBehavior.OpenRoot,
            ),
            shellState.consumeNavigationRequest(),
        )
    }
}
