package com.ticketbox.data.repository

import androidx.test.ext.junit.runners.AndroidJUnit4
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.local.PendingMutationType
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import org.junit.runner.RunWith

/** The real Room recovery predicates must preserve the original refund condition. */
@RunWith(AndroidJUnit4::class)
class ExpenseOffsetRoomIdentityTest {
    private val fixture = ExpenseCorrectionConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)

    @After fun close() = fixture.close()

    @Test
    fun roomKeepsRefundIdentityAcrossReopenCascadeAndRecoveryWithoutBlockingOtherTypes() = runBlocking {
        fixture.reopen()
        val id = fixture.outbox.enqueue(PendingMutationType.CreateExpenseOffset, "expense:42",
            """{"kind":"refund","original_amount_minor":1000,"accounting_date":"2026-09-03","reason":"Original refund","expected_row_version":7}""",
            7, "original-refund-key")
        val original = fixture.stored().single()
        fixture.reopen()
        fixture.outbox.cascadeFreshToken("expense:42", 8)
        assertEquals(original, fixture.stored().single())
        fixture.outbox.markConflict(id, "state_conflict")
        assertFalse(fixture.outbox.resolveConflict(id, ConflictResolution.KeepMine(8)))
        assertEquals("conflict", fixture.stored().single()["status"])
        fixture.outbox.markFailed(id, "network unavailable")
        assertFalse(fixture.outbox.resolveFailed(id, FailedResolution.Retry(freshToken = 8)))
        assertEquals("failed", fixture.stored().single()["status"])
        assertTrue(fixture.outbox.resolveFailed(id, FailedResolution.Retry()))
        assertEquals("pending", fixture.stored().single()["status"])
        for (column in listOf("id", "type", "targetId", "payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId")) {
            assertEquals(original[column], fixture.stored().single()[column])
        }

        val patch = fixture.outbox.enqueue(PendingMutationType.PatchExpense, "expense:42", "{\"note\":\"Original patch\"}", 7, "patch-key")
        fixture.outbox.cascadeFreshToken("expense:42", 9)
        assertEquals("9", fixture.stored().single { it["id"] == patch.toString() }["expectedRowVersion"])
        assertEquals("7", fixture.stored().single { it["id"] == id.toString() }["expectedRowVersion"])
        fixture.outbox.markConflict(patch, "state_conflict")
        assertTrue(fixture.outbox.resolveConflict(patch, ConflictResolution.KeepMine(10)))
        fixture.outbox.markFailed(patch, "network unavailable")
        assertTrue(fixture.outbox.resolveFailed(patch, FailedResolution.Retry(freshToken = 11)))
        assertEquals("11", fixture.stored().single { it["id"] == patch.toString() }["expectedRowVersion"])
        assertEquals(0, fixture.network.calls.size)
    }
}
