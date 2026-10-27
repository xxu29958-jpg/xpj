package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class DebtAdjustmentCreateRequest(
    @param:Json(name = "amount_cents")
    val amountCents: Long,
    val reason: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class DebtKindSetRequest(
    @param:Json(name = "debt_kind")
    val debtKind: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class DebtVoidCreateRequest(
    val reason: String,
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

data class RepaymentCreateRequest(
    val amountCents: Long,
    val expectedRowVersion: Long,
    val paidAt: String? = null,
    val timeInput: ExpenseTimeInput? = null,
)

data class RepaymentDraftConfirmRequest(
    val targetDebtPublicId: String,
    val expectedRowVersion: Long,
    val originalCurrency: String? = null,
    val originalAmount: String? = null,
    val timeInput: ExpenseTimeInput? = null,
    val targetChoiceExplicit: Boolean? = null,
)

@JsonClass(generateAdapter = true)
data class RepaymentVoidCreateRequest(
    @param:Json(name = "repayment_public_id") val repaymentPublicId: String,
    val reason: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
)
