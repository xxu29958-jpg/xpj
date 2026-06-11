package com.ticketbox.domain.model

import java.time.Instant
import java.time.OffsetDateTime

/**
 * ADR-0029 bill split domain models — separate sender and receiver
 * shapes to mirror the backend's strict DTO separation.
 *
 * - [BillSplitSent]: an invitation as seen by the person who created
 *   it. Carries who they sent it to and a reference to their own
 *   expense, but never the receiver's chosen ledger.
 * - [BillSplitInbox]: an invitation as seen by the person who received
 *   it. Carries who sent it, but never the sender's expense id or
 *   ledger.
 */

object BillSplitStatusValues {
    const val INVITED = "invited"
    const val ACCEPTED = "accepted"
    const val REJECTED = "rejected"
    const val CANCELLED = "cancelled"
    const val EXPIRED = "expired"
}

data class BillSplitSent(
    val publicId: String,
    val status: String,
    val amountCents: Long,
    val merchantSnapshot: String?,
    val categorySuggestion: String?,
    val expenseTimeSnapshot: String?,
    val expiresAt: String,
    val createdAt: String,
    val acceptedAt: String?,
    val rejectedAt: String?,
    val cancelledAt: String?,
    val expiredAt: String?,
    val receiverAccountId: Long,
    val receiverDisplayNameSnapshot: String?,
    val senderExpenseId: Long,
)

data class BillSplitInbox(
    val publicId: String,
    val status: String,
    val amountCents: Long,
    val merchantSnapshot: String?,
    val categorySuggestion: String?,
    val expenseTimeSnapshot: String?,
    val expiresAt: String,
    val createdAt: String,
    val acceptedAt: String?,
    val rejectedAt: String?,
    val cancelledAt: String?,
    val expiredAt: String?,
    val senderAccountId: Long,
    val senderDisplayName: String,
)

/**
 * Local 已过期 derivation for an invited inbox row, mirroring the /web inbox
 * page (`web_bill_split.py`: ``is_expired = ensure_utc(expires_at) <= now_utc()
 * if status == "invited" else False``). A pure UTC-instant comparison — the
 * accounting timezone plays no part. An unparsable [BillSplitInbox.expiresAt]
 * fails open (returns false): the row degrades to its server status instead of
 * locking actions early. Sent rows deliberately get no local derivation on
 * either surface (/web's sent page renders the raw status too); the server
 * sweeper stays the authority that actually flips rows to `expired`.
 */
fun BillSplitInbox.isInviteLocallyExpired(now: Instant = Instant.now()): Boolean {
    if (status != BillSplitStatusValues.INVITED) return false
    val expiry = runCatching { Instant.parse(expiresAt) }
        .recoverCatching { OffsetDateTime.parse(expiresAt).toInstant() }
        .getOrNull() ?: return false
    return !expiry.isAfter(now)
}
