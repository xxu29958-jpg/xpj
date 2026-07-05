package com.ticketbox.ui.screens.expense

import com.ticketbox.domain.model.ItemsSumStatus
import kotlin.test.Test
import kotlin.test.assertEquals

class ExpenseDetailReconcileStatusTest {
    @Test
    fun nullMismatchStaysUnknownEvenWhenItemsStatusMatched() {
        assertEquals(
            ExpenseDetailReconcileStatus.Unknown,
            resolveExpenseDetailReconcileStatus(
                mismatchCents = null,
                itemsSumStatus = ItemsSumStatus.MATCHED,
            ),
        )
    }

    @Test
    fun zeroMismatchIsMatched() {
        assertEquals(
            ExpenseDetailReconcileStatus.Matched,
            resolveExpenseDetailReconcileStatus(mismatchCents = 0L),
        )
    }

    @Test
    fun nonZeroMismatchIsDiff() {
        assertEquals(
            ExpenseDetailReconcileStatus.Diff,
            resolveExpenseDetailReconcileStatus(mismatchCents = -300L),
        )
    }

    @Test
    fun itemMismatchStatusIsDiff() {
        assertEquals(
            ExpenseDetailReconcileStatus.Diff,
            resolveExpenseDetailReconcileStatus(
                mismatchCents = 250L,
                itemsSumStatus = ItemsSumStatus.MISMATCH_ACKNOWLEDGED,
            ),
        )
    }
}
