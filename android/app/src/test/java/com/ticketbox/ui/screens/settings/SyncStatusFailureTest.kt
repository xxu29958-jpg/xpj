package com.ticketbox.ui.screens.settings

import kotlin.test.Test
import kotlin.test.assertFalse
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
}
