package com.ticketbox.ui.screens.pending

import kotlin.test.Test
import kotlin.test.assertEquals

class PendingQueueOverviewTest {
    @Test
    fun duplicatePriorityWinsOverOtherReviewSignals() {
        val model = pendingQueueOverviewModel(
            PendingQueueCounts(
                all = 8,
                needsAmount = 2,
                needsMerchant = 1,
                duplicate = 1,
                readyToConfirm = 3,
            ),
        )

        assertEquals(PendingQueuePriority.Duplicate, model.priority)
        assertEquals(5, model.reviewCount)
    }

    @Test
    fun amountPriorityWinsBeforeMerchantAndReady() {
        val model = pendingQueueOverviewModel(
            PendingQueueCounts(
                all = 5,
                needsAmount = 1,
                needsMerchant = 2,
                duplicate = 0,
                readyToConfirm = 2,
            ),
        )

        assertEquals(PendingQueuePriority.Amount, model.priority)
        assertEquals(3, model.reviewCount)
    }

    @Test
    fun merchantPriorityShowsWhenMerchantIsTheFirstBlockingSignal() {
        val model = pendingQueueOverviewModel(
            PendingQueueCounts(
                all = 4,
                needsAmount = 0,
                needsMerchant = 2,
                duplicate = 0,
                readyToConfirm = 1,
            ),
        )

        assertEquals(PendingQueuePriority.Merchant, model.priority)
        assertEquals(3, model.reviewCount)
    }

    @Test
    fun readyPriorityShowsBatchableWork() {
        val model = pendingQueueOverviewModel(
            PendingQueueCounts(
                all = 3,
                needsAmount = 0,
                needsMerchant = 0,
                duplicate = 0,
                readyToConfirm = 3,
            ),
        )

        assertEquals(PendingQueuePriority.Ready, model.priority)
        assertEquals(0, model.reviewCount)
    }

    @Test
    fun emptyPriorityClampsInvalidCounts() {
        val model = pendingQueueOverviewModel(
            PendingQueueCounts(
                all = -1,
                needsAmount = -2,
                needsMerchant = -3,
                duplicate = -4,
                readyToConfirm = 9,
            ),
        )

        assertEquals(PendingQueuePriority.Empty, model.priority)
        assertEquals(0, model.reviewCount)
        assertEquals(0, model.readyCount)
    }
}
