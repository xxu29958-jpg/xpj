package com.ticketbox.ui.screens.pending

import kotlin.test.Test
import kotlin.test.assertEquals

class PendingActionSummaryTest {
    @Test
    fun missingInformationStaysSeparateFromDuplicateRisk() {
        val model = pendingQueueOverviewModel(
            PendingQueueCounts(
                all = 6,
                needsAmount = 1,
                needsMerchant = 1,
                duplicate = 2,
                readyToConfirm = 2,
                needsCategory = 1,
                needsInformation = 2,
            ),
        )

        assertEquals(2, model.needsInformation)
        assertEquals(2, model.duplicate)
        assertEquals(2, model.readyCount)
    }
}
