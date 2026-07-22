package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.DataQualitySummary
import kotlin.test.Test
import kotlin.test.assertEquals

class PendingOverviewCardTest {
    @Test
    fun everyVisibleQualityMetricHasTypedRemediation() {
        val metrics = pendingOverviewMetrics(
            DataQualitySummary(
                pendingTotal = 9,
                missingAmount = 1,
                missingMerchant = 2,
                missingCategory = 3,
                suspectedDuplicates = 4,
                confirmedWithoutImage = 5,
                readyToConfirm = 6,
                oldestPendingAgeDays = 2,
                generatedAt = "2026-07-18T00:00:00Z",
            ),
        )

        assertEquals(
            listOf(
                DataQualityRemediation.InboxReady,
                DataQualityRemediation.InboxMissingAmount,
                DataQualityRemediation.InboxMissingMerchant,
                DataQualityRemediation.InboxMissingCategory,
                DataQualityRemediation.InboxDuplicate,
                DataQualityRemediation.TransactionsConfirmedWithoutImage,
            ),
            metrics.map(PendingOverviewMetric::primaryRemediation),
        )
        assertEquals(
            DataQualityRemediation.TransactionsMissingCategory,
            metrics.single { it.primaryRemediation == DataQualityRemediation.InboxMissingCategory }
                .secondaryRemediation,
        )
    }

    @Test
    fun zeroCountMetricsDoNotCreateDeadActions() {
        val metrics = pendingOverviewMetrics(
            DataQualitySummary(
                pendingTotal = 0,
                missingAmount = 0,
                missingMerchant = 0,
                missingCategory = 0,
                suspectedDuplicates = 0,
                confirmedWithoutImage = 0,
                readyToConfirm = 0,
                oldestPendingAgeDays = null,
                generatedAt = "2026-07-18T00:00:00Z",
            ),
        )

        assertEquals(emptyList(), metrics)
    }
}
