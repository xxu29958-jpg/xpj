package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * Canonical append-only correction attached to one repayment fact.
 *
 * This is audit data, not a deletion marker synthesized by the client. The backend keeps the
 * original repayment and exposes this nested fact when that repayment has been voided.
 */
data class RepaymentVoidFactDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val reason: String,
    @param:Json(name = "created_at")
    val createdAt: String,
)

/**
 * One canonical repayment fact returned by `GET /api/debts/{id}/repayments`.
 *
 * The optional original-currency fields are provenance only. [status] and [voidFact] come from the
 * server's append-only Repayment/RepaymentVoid projection; the client never infers either from the
 * parent Debt balance.
 */
data class RepaymentFactDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    @param:Json(name = "original_currency_code")
    val originalCurrencyCode: String? = null,
    @param:Json(name = "original_amount_minor")
    val originalAmountMinor: Long? = null,
    @param:Json(name = "exchange_rate_to_cny")
    val exchangeRateToCny: String? = null,
    @param:Json(name = "exchange_rate_date")
    val exchangeRateDate: String? = null,
    @param:Json(name = "exchange_rate_source")
    val exchangeRateSource: String? = null,
    @param:Json(name = "paid_at")
    val paidAt: String,
    @param:Json(name = "created_at")
    val createdAt: String,
    val status: String,
    @param:Json(name = "void_fact")
    val voidFact: RepaymentVoidFactDto? = null,
)

/** Bounded first-page response for one authorized Debt's restart-safe repayment history. */
data class RepaymentFactListResponseDto(
    @param:Json(name = "debt_public_id")
    val debtPublicId: String,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String,
    val items: List<RepaymentFactDto>,
    val page: Int,
    @param:Json(name = "page_size")
    val pageSize: Int,
    val total: Int,
)
