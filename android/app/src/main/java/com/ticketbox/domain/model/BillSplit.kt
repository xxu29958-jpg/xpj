package com.ticketbox.domain.model

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
