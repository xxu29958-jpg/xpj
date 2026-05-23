package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * ADR-0029 bill split DTOs — strictly separate Sent and Inbox shapes.
 * See backend ``schemas/_bill_split.py`` for canonical reference.
 */

data class BillSplitInviteRequestDto(
    @param:Json(name = "receiver_account_id")
    val receiverAccountId: Long,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
)

data class BillSplitAcceptRequestDto(
    @param:Json(name = "target_ledger_id")
    val targetLedgerId: String,
)

/** Sender view DTO — receiver_ledger_id absent by design (privacy). */
data class BillSplitSentDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val status: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    @param:Json(name = "merchant_snapshot")
    val merchantSnapshot: String?,
    @param:Json(name = "category_suggestion")
    val categorySuggestion: String?,
    @param:Json(name = "expense_time_snapshot")
    val expenseTimeSnapshot: String?,
    @param:Json(name = "expires_at")
    val expiresAt: String,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "accepted_at")
    val acceptedAt: String?,
    @param:Json(name = "rejected_at")
    val rejectedAt: String?,
    @param:Json(name = "cancelled_at")
    val cancelledAt: String?,
    @param:Json(name = "expired_at")
    val expiredAt: String?,
    @param:Json(name = "receiver_account_id")
    val receiverAccountId: Long,
    @param:Json(name = "receiver_display_name_snapshot")
    val receiverDisplayNameSnapshot: String?,
    @param:Json(name = "sender_expense_id")
    val senderExpenseId: Long,
)

/** Receiver view DTO — sender_ledger_id / sender_expense_id absent. */
data class BillSplitInboxDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val status: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    @param:Json(name = "merchant_snapshot")
    val merchantSnapshot: String?,
    @param:Json(name = "category_suggestion")
    val categorySuggestion: String?,
    @param:Json(name = "expense_time_snapshot")
    val expenseTimeSnapshot: String?,
    @param:Json(name = "expires_at")
    val expiresAt: String,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "accepted_at")
    val acceptedAt: String?,
    @param:Json(name = "rejected_at")
    val rejectedAt: String?,
    @param:Json(name = "cancelled_at")
    val cancelledAt: String?,
    @param:Json(name = "expired_at")
    val expiredAt: String?,
    @param:Json(name = "sender_account_id")
    val senderAccountId: Long,
    @param:Json(name = "sender_display_name")
    val senderDisplayName: String,
)

data class BillSplitSentListResponseDto(
    val items: List<BillSplitSentDto>,
)

data class BillSplitInboxListResponseDto(
    val items: List<BillSplitInboxDto>,
)
