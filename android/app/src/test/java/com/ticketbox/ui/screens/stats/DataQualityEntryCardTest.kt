package com.ticketbox.ui.screens.stats

import com.ticketbox.domain.model.DataQualitySummary
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

class DataQualityEntryCardTest {
    @Test
    fun duplicateOnlyAttentionCarriesTheDuplicateCountIntoEntryCopy() {
        val summary = DataQualitySummary(
            pendingTotal = 0,
            missingAmount = 0,
            missingMerchant = 0,
            missingCategory = 0,
            missingCategoryPending = 0,
            missingCategoryConfirmed = 0,
            suspectedDuplicates = 3,
            confirmedWithoutImage = 0,
            readyToConfirm = 0,
            readyToConfirmCategorized = 0,
            oldestPendingAgeDays = null,
            generatedAt = "2026-07-18T00:00:00Z",
        )

        assertTrue(summary.hasDataQualityAttention())
        assertEquals(
            DataQualityAttentionCounts(
                pendingTotal = 0,
                missingCategory = 0,
                suspectedDuplicates = 3,
                confirmedWithoutImage = 0,
            ),
            summary.toDataQualityAttentionCounts(),
        )
    }
}
