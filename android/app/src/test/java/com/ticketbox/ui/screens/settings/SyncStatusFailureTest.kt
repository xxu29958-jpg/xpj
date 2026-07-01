package com.ticketbox.ui.screens.settings

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.OutboxStatus
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0042 §4.10: a reaper age-cap expiry is terminal — the FailedCard hides
 * Retry for it (replaying would hit a server-purged idempotency key, and the
 * next drain would just re-reap the row). Every other failure marker stays
 * retryable.
 */
class SyncStatusFailureTest {

    @Test
    fun `reaper-expired marker is terminal (no retry)`() {
        assertTrue(isExpiredFailure("outbox_row_expired"))
    }

    @Test
    fun `other failure markers stay retryable`() {
        assertFalse(isExpiredFailure("max_attempts_exceeded(10/10): server 503"))
        assertFalse(isExpiredFailure("no_dispatcher_registered:replace_splits"))
        assertFalse(isExpiredFailure(null))
    }

    @Test
    fun `overview counts come from outbox status`() {
        val overview = syncStatusOverview(
            OutboxStatus(
                queueDepth = 3,
                conflicts = listOf(row(id = 1), row(id = 2)),
                failed = listOf(row(id = 3)),
            ),
        )

        assertEquals(3, overview.queuedCount)
        assertEquals(2, overview.conflictCount)
        assertEquals(1, overview.failedCount)
        assertEquals(3, overview.needsActionCount)
        assertFalse(overview.isSettled)
    }

    @Test
    fun `overview clamps invalid queue depth and marks settled`() {
        val overview = syncStatusOverview(
            OutboxStatus(
                queueDepth = -1,
                conflicts = emptyList(),
                failed = emptyList(),
            ),
        )

        assertEquals(0, overview.queuedCount)
        assertTrue(overview.isSettled)
    }

    private fun row(id: Long) = OutboxRow(
        id = id,
        serverUrl = "http://127.0.0.1:8000",
        ledgerId = "ledger",
        type = PendingMutationType.PatchExpense,
        targetId = "expense:$id",
        payloadJson = "{}",
        expectedRowVersion = 1L,
        status = PendingMutationStatus.Conflict,
        retryCount = 0,
        lastError = null,
        createdAt = "2026-07-01T00:00:00Z",
        attemptedAt = null,
        completedAt = null,
    )
}
