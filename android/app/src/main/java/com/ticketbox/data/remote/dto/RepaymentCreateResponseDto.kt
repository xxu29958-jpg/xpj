package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * Response for `POST /api/debts/{id}/repayments`.
 *
 * The backend returns the fold-after Debt plus [repaymentPublicId]. Keeping that fact id is
 * load-bearing: `RepaymentVoidCreateRequest` targets the repayment, not the parent Debt. This DTO
 * intentionally does not reuse [DebtDto], whose `DebtResponse` contract has no
 * `repayment_public_id`.
 */
data class RepaymentCreateResponseDto(
    @param:Json(name = "public_id")
    val publicId: String,
    @param:Json(name = "ledger_id")
    val ledgerId: String? = null,
    val direction: String,
    @param:Json(name = "counterparty_type")
    val counterpartyType: String,
    @param:Json(name = "counterparty_account_id")
    val counterpartyAccountId: Long? = null,
    @param:Json(name = "counterparty_label")
    val counterpartyLabel: String? = null,
    @param:Json(name = "principal_amount_cents")
    val principalAmountCents: Long,
    @param:Json(name = "remaining_amount_cents")
    val remainingAmountCents: Long,
    @param:Json(name = "paid_amount_cents")
    val paidAmountCents: Long,
    val status: String,
    @param:Json(name = "source_type")
    val sourceType: String,
    @param:Json(name = "source_id")
    val sourceId: String? = null,
    @param:Json(name = "debt_kind")
    val debtKind: String = "unspecified",
    @param:Json(name = "installment_count")
    val installmentCount: Long? = null,
    @param:Json(name = "installment_period_months")
    val installmentPeriodMonths: Long? = null,
    @param:Json(name = "installment_payoff_date")
    val installmentPayoffDate: String? = null,
    @param:Json(name = "installment_paid_count")
    val installmentPaidCount: Long? = null,
    @param:Json(name = "home_currency_code")
    val homeCurrencyCode: String,
    @param:Json(name = "original_currency_code")
    val originalCurrencyCode: String? = null,
    @param:Json(name = "original_amount_minor")
    val originalAmountMinor: Long? = null,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
    @param:Json(name = "row_version")
    val rowVersion: Long,
    @param:Json(name = "viewer_is_debtor")
    val viewerIsDebtor: Boolean? = null,
    @param:Json(name = "is_forgiven")
    val isForgiven: Boolean = false,
    @param:Json(name = "repayment_public_id")
    val repaymentPublicId: String,
)
