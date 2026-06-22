package com.ticketbox.domain.model

import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * issue #65 slice 5: a not-yet-synced offline create has no server id, so a
 * cross-ledger split invitation (which addresses the sender expense by server id)
 * can't be issued until it syncs — [Expense.canInitiateBillSplit] must return
 * false for a ``pendingSync`` row even though it is confirmed + has an amount.
 */
class ExpenseCanInitiateBillSplitTest {

    private fun expense(
        pendingSync: Boolean = false,
        status: String = "confirmed",
        amountCents: Long? = 1000,
        source: String = ExpenseSourceValues.MANUAL_ENTRY,
    ): Expense = Expense(
        id = 1L,
        publicId = "test-1",
        amountCents = amountCents,
        merchant = "商家",
        category = "餐饮",
        note = null,
        source = source,
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
        status = status,
        expenseTime = null,
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-01T00:00:00Z",
        rowVersion = 1L,
        confirmedAt = "2026-05-01T00:00:00Z",
        rejectedAt = null,
        pendingSync = pendingSync,
    )

    @Test
    fun aSyncedConfirmedRowCanInitiateBillSplit() {
        assertTrue(expense(pendingSync = false).canInitiateBillSplit(readOnly = false))
    }

    @Test
    fun aPendingSyncRowCannotInitiateBillSplit() {
        assertFalse(
            expense(pendingSync = true).canInitiateBillSplit(readOnly = false),
            "a not-yet-synced offline create has no server id to split from",
        )
    }
}
