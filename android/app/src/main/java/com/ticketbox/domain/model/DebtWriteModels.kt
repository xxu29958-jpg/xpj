package com.ticketbox.domain.model

data class DebtAdjustmentCreateRequest(
    val amountCents: Long,
    val reason: String,
    val expectedRowVersion: Long,
)

data class DebtKindSetRequest(
    val debtKind: String,
    val expectedRowVersion: Long,
)

data class DebtVoidCreateRequest(
    val reason: String,
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

data class RepaymentVoidCreateRequest(
    val repaymentPublicId: String,
    val reason: String,
    val expectedRowVersion: Long,
)
