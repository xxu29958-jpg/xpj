package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.DataQualitySummary
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class PendingOverviewCardTest {
    @Test
    fun everyVisibleQualityMetricHasTypedRemediation() {
        val metrics = pendingOverviewMetrics(
            baseSummary.copy(
                pendingTotal = 9,
                missingAmount = 1,
                missingMerchant = 2,
                missingCategory = 3,
                missingCategoryPending = 2,
                missingCategoryConfirmed = 1,
                suspectedDuplicates = 4,
                confirmedWithoutImage = 5,
                readyToConfirmCategorized = 4,
            ),
        )

        assertEquals(
            listOf(
                DataQualityRemediation.InboxReady,
                DataQualityRemediation.InboxMissingAmount,
                DataQualityRemediation.InboxMissingMerchant,
                DataQualityRemediation.InboxMissingCategory,
                DataQualityRemediation.TransactionsMissingCategory,
                DataQualityRemediation.InboxDuplicate,
                DataQualityRemediation.TransactionsConfirmedWithoutImage,
            ),
            metrics.map(PendingOverviewMetric::primaryRemediation),
        )
    }

    @Test
    fun zeroCountMetricsDoNotCreateDeadActions() {
        val metrics = pendingOverviewMetrics(baseSummary)

        assertEquals(emptyList(), metrics)
    }

    @Test
    fun readyLineUsesTheInboxLandingCaliber() {
        // Backend ready_to_confirm doesn't check category, but the inbox
        // ReadyToConfirm filter routes those rows to quick-category first —
        // the line must advertise the categorized count the tap lands on.
        val metrics = pendingOverviewMetrics(
            baseSummary.copy(readyToConfirm = 6, readyToConfirmCategorized = 1),
        )

        val readyLine = metrics.single { it.primaryRemediation == DataQualityRemediation.InboxReady }
        assertEquals(1, readyLine.value)
    }

    @Test
    fun readyLineHidesWhenEveryBackendReadyRowNeedsCategory() {
        val metrics = pendingOverviewMetrics(
            baseSummary.copy(readyToConfirm = 3, readyToConfirmCategorized = 0),
        )

        assertNull(metrics.firstOrNull { it.primaryRemediation == DataQualityRemediation.InboxReady })
    }

    @Test
    fun missingCategorySplitsIntoPerStatusLinesMatchingTheirDestinations() {
        val metrics = pendingOverviewMetrics(
            baseSummary.copy(
                missingCategory = 5,
                missingCategoryPending = 3,
                missingCategoryConfirmed = 2,
            ),
        )

        val inboxLine = metrics.single { it.primaryRemediation == DataQualityRemediation.InboxMissingCategory }
        val ledgerLine = metrics.single { it.primaryRemediation == DataQualityRemediation.TransactionsMissingCategory }
        assertEquals(3, inboxLine.value)
        assertEquals(2, ledgerLine.value)
    }

    @Test
    fun confirmedOnlyMissingCategoryDoesNotRouteToAnEmptyInbox() {
        val metrics = pendingOverviewMetrics(
            baseSummary.copy(missingCategory = 2, missingCategoryConfirmed = 2),
        )

        assertNull(metrics.firstOrNull { it.primaryRemediation == DataQualityRemediation.InboxMissingCategory })
        val ledgerLine = metrics.single { it.primaryRemediation == DataQualityRemediation.TransactionsMissingCategory }
        assertEquals(2, ledgerLine.value)
    }

    @Test
    fun pendingOnlyMissingCategoryDoesNotRouteToAnEmptyLedger() {
        val metrics = pendingOverviewMetrics(
            baseSummary.copy(missingCategory = 2, missingCategoryPending = 2),
        )

        assertNull(metrics.firstOrNull { it.primaryRemediation == DataQualityRemediation.TransactionsMissingCategory })
        val inboxLine = metrics.single { it.primaryRemediation == DataQualityRemediation.InboxMissingCategory }
        assertEquals(2, inboxLine.value)
    }
}

private val baseSummary = DataQualitySummary(
    pendingTotal = 0,
    missingAmount = 0,
    missingMerchant = 0,
    missingCategory = 0,
    missingCategoryPending = 0,
    missingCategoryConfirmed = 0,
    suspectedDuplicates = 0,
    confirmedWithoutImage = 0,
    readyToConfirm = 0,
    readyToConfirmCategorized = 0,
    oldestPendingAgeDays = null,
    generatedAt = "2026-07-18T00:00:00Z",
)
