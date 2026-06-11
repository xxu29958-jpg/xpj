package com.ticketbox.domain.model

import java.time.Instant
import kotlin.test.Test
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * [isInviteLocallyExpired] mirrors /web's inbox derivation
 * (`web_bill_split.py`: `expires_at <= now`, invited rows only, pure UTC
 * instants). These pin the boundary (`<=` not `<`), the status guard, the
 * offset-format recover branch and the fail-open on unparsable input.
 */
class BillSplitExpiryTest {
    private val now: Instant = Instant.parse("2026-06-12T00:00:00Z")

    @Test
    fun invitedRowPastExpiryIsLocallyExpired() {
        assertTrue(inboxRow(expiresAt = "2026-06-11T23:59:59Z").isInviteLocallyExpired(now))
    }

    @Test
    fun invitedRowBeforeExpiryIsNotExpired() {
        assertFalse(inboxRow(expiresAt = "2026-06-12T00:00:01Z").isInviteLocallyExpired(now))
    }

    @Test
    fun expiryExactlyAtNowCountsAsExpired() {
        // Pins `expires_at <= now` (the /web comparison), not `<`.
        assertTrue(inboxRow(expiresAt = "2026-06-12T00:00:00Z").isInviteLocallyExpired(now))
    }

    @Test
    fun nonInvitedRowNeverDerivesExpiry() {
        val row = inboxRow(status = BillSplitStatusValues.ACCEPTED, expiresAt = "2026-06-11T23:59:59Z")
        assertFalse(row.isInviteLocallyExpired(now))
    }

    @Test
    fun offsetFormatTimestampParsesViaRecoverBranch() {
        assertTrue(inboxRow(expiresAt = "2026-06-11T23:59:59+00:00").isInviteLocallyExpired(now))
    }

    @Test
    fun unparsableExpiryFailsOpenToNotExpired() {
        assertFalse(inboxRow(expiresAt = "not-a-timestamp").isInviteLocallyExpired(now))
    }

    private fun inboxRow(
        status: String = BillSplitStatusValues.INVITED,
        expiresAt: String,
    ): BillSplitInbox = BillSplitInbox(
        publicId = "bs-1",
        status = status,
        amountCents = 1200L,
        merchantSnapshot = null,
        categorySuggestion = null,
        expenseTimeSnapshot = null,
        expiresAt = expiresAt,
        createdAt = "2026-06-01T00:00:00Z",
        acceptedAt = null,
        rejectedAt = null,
        cancelledAt = null,
        expiredAt = null,
        senderAccountId = 1L,
        senderDisplayName = "甲",
    )
}
