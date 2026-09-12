package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.test.runTest
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ExpenseUndoOriginalRecoveryTest {
    @Test fun successorCascadeAndExplicitRecoveryCannotRetargetAnUndoToALaterRejection() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val id = outbox.enqueue(PendingMutationType.UndoExpense, "expense:42", "{}", 3, "undo-original")
        val original = requireNotNull(dao.rows[id])
        outbox.cascadeFreshToken("expense:42", 7)
        assertEquals(original, dao.rows[id])
        outbox.markConflict(id, "A later rejection changed the fact")
        val conflicted = requireNotNull(dao.rows[id])
        assertFalse(outbox.resolveConflict(id, ConflictResolution.KeepMine(7)))
        assertEquals(conflicted, dao.rows[id])
        assertTrue(outbox.resolveConflict(id, ConflictResolution.DropMine))
    }

    @Test fun RefusedUndoAndAnAcceptedRejectionWithoutItsOriginalReceiptCannotBeGenericRetries() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        for ((type, code) in listOf(PendingMutationType.UndoExpense to "expense_not_found",
            PendingMutationType.RejectExpense to EXPENSE_REJECTION_ORIGINAL_REQUIRES_REVIEW)) {
            val id = outbox.enqueue(type, "expense:42", "{}", 3, "original-${type.wireValue}")
            outbox.markFailed(id, code)
            val failed = requireNotNull(dao.rows[id])
            assertFalse(outbox.resolveFailed(id, FailedResolution.Retry()))
            assertFalse(outbox.resolveFailed(id, FailedResolution.Retry(9)))
            assertEquals(failed, dao.rows[id])
            assertTrue(outbox.resolveFailed(id, FailedResolution.Drop))
        }
    }
}
