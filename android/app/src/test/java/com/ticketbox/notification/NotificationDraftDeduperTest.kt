package com.ticketbox.notification

import com.ticketbox.domain.model.NotificationDraft
import com.ticketbox.domain.model.NotificationDraftSource
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class NotificationDraftDeduperTest {
    @Test
    fun failedDraftCanBeRetriedImmediately() {
        var now = 1_000L
        val deduper = NotificationDraftDeduper(clockMillis = { now }, ttlMillis = 30 * 60 * 1000L)
        val draft = draft()

        assertTrue(deduper.tryReserve(draft))
        assertFalse(deduper.tryReserve(draft))

        deduper.release(draft)

        assertTrue(deduper.tryReserve(draft))
    }

    @Test
    fun successfulDraftSuppressesDuplicatesUntilTtlExpires() {
        var now = 1_000L
        val deduper = NotificationDraftDeduper(clockMillis = { now }, ttlMillis = 10L)
        val draft = draft()

        assertTrue(deduper.tryReserve(draft))
        assertFalse(deduper.tryReserve(draft))

        now += 11L

        assertTrue(deduper.tryReserve(draft))
    }

    private fun draft(): NotificationDraft = NotificationDraft(
        source = NotificationDraftSource.WeChat,
        amountCents = 2580L,
        merchant = "星巴克",
        category = null,
        expenseTime = "2026-05-13T08:00:00Z",
    )
}
