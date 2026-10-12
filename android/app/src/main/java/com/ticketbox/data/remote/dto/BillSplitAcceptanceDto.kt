package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/** Acceptance ACK has its own contract; list and rejection responses carry no target receipt. */
@com.squareup.moshi.JsonClass(generateAdapter = true)
data class BillSplitAcceptanceDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val status: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String,
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
    @param:Json(name = "received_bill")
    val receivedBill: BillSplitReceivedBillDto? = null,
    @param:Json(name = "accepted_target_ledger_id") val acceptedTargetLedgerId: String? = null,
    @param:Json(name = "original_currency_code") val originalCurrencyCode: String? = null,
    @param:Json(name = "original_amount_minor") val originalAmountMinor: Long? = null,
    @param:Json(name = "accounting_time_snapshot") val accountingTimeSnapshot: ExpenseAccountingTimeDto? = null,
)
