package com.ticketbox.ui.screens

import com.ticketbox.domain.model.Expense
import com.ticketbox.ui.screens.ledger.shouldCompactLedgerDayGroups
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * Pure-JVM coverage for the ledger day-group subtotal (batch 8 "扫读节奏").
 * [LedgerExpenseGroup.dayTotalCents] is the value rendered on each day header,
 * so the sum (and its null-amount handling) is pinned here. The grouping +
 * label resolution path ([groupLedgerExpenses]) needs Android Resources and is
 * exercised by instrumented tests; this only targets the arithmetic.
 */
class LedgerGroupingTest {
    @Test
    fun dayTotalSumsConfirmedAmounts() {
        val group = LedgerExpenseGroup(
            key = "2026-05-17",
            label = "5月17日 六",
            items = listOf(
                expense(id = 1, amountCents = 1200),
                expense(id = 2, amountCents = 3000),
                expense(id = 3, amountCents = 450),
            ),
        )

        assertEquals(4650L, group.dayTotalCents)
    }

    @Test
    fun dayTotalTreatsNullAmountsAsZero() {
        val group = LedgerExpenseGroup(
            key = "2026-05-17",
            label = "5月17日 六",
            items = listOf(
                expense(id = 1, amountCents = 1200),
                expense(id = 2, amountCents = null),
                expense(id = 3, amountCents = 800),
            ),
        )

        // The null-amount row contributes 0, not a crash or a skipped group.
        assertEquals(2000L, group.dayTotalCents)
    }

    @Test
    fun dayTotalIsZeroForAnEmptyDay() {
        val group = LedgerExpenseGroup(key = "unknown", label = "未设置日期", items = emptyList())

        assertEquals(0L, group.dayTotalCents)
    }

    @Test
    fun dayGroupExposesItemCountForFoldedHeaders() {
        val group = LedgerExpenseGroup(
            key = "2026-05-17",
            label = "5月17日 六",
            items = listOf(
                expense(id = 1, amountCents = 1200),
                expense(id = 2, amountCents = 3000),
            ),
        )

        assertEquals(2, group.itemCount)
    }

    @Test
    fun compactDayGroupsOnlyStartsForLongLedgerLists() {
        assertFalse(shouldCompactLedgerDayGroups(groupCount = 4, itemCount = 8))
        assertTrue(shouldCompactLedgerDayGroups(groupCount = 4, itemCount = 9))
        assertTrue(shouldCompactLedgerDayGroups(groupCount = 2, itemCount = 13))
    }
}

private fun expense(id: Long, amountCents: Long?): Expense = Expense(
    id = id,
    publicId = "exp-$id",
    amountCents = amountCents,
    merchant = "商家$id",
    category = "餐饮",
    note = null,
    source = "manual",
    imagePath = null,
    thumbnailPath = null,
    imageHash = null,
    rawText = null,
    confidence = null,
    duplicateStatus = "none",
    duplicateOfId = null,
    duplicateReason = null,
    tags = null,
    valueScore = null,
    regretScore = null,
    status = "confirmed",
    expenseTime = "2026-05-17T08:00:00Z",
    createdAt = "2026-05-17T08:00:00Z",
    updatedAt = "2026-05-17T08:00:00Z",
    rowVersion = 1L,
    confirmedAt = "2026-05-17T08:01:00Z",
    rejectedAt = null,
)
