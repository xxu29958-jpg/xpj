package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass
import com.ticketbox.domain.model.BalanceObservation
import com.ticketbox.domain.model.CreditApplications
import com.ticketbox.domain.model.CreditFeeView
import com.ticketbox.domain.model.CreditTerms
import com.ticketbox.domain.model.FundMovement

@JsonClass(generateAdapter = true)
data class FinancialAccountDto(
    @param:Json(name = "public_id") val publicId: String,
    val name: String,
    @param:Json(name = "ledger_id") val ledgerId: String,
    @param:Json(name = "calendar_revision") val calendarRevision: Long,
    val kind: String,
    @param:Json(name = "currency_code") val currencyCode: String,
    val visibility: String,
    val institution: String?,
    val tail: String?,
    @param:Json(name = "row_version") val rowVersion: Long,
    val archived: Boolean,
    @param:Json(name = "balance_minor") val balanceMinor: Long?,
    @param:Json(name = "recorded_change_minor") val recordedChangeMinor: Long,
    @param:Json(name = "opening_date") val openingDate: String,
    @param:Json(name = "opening_source") val openingSource: String,
    @param:Json(name = "debt_public_id") val debtPublicId: String?,
    @param:Json(name = "can_edit") val canEdit: Boolean,
    val movements: List<FundMovement> = emptyList(),
    @param:Json(name = "fee_obligations") val feeObligations: List<CreditFeeView> = emptyList(),
    @param:Json(name = "credit_applications") val creditApplications: CreditApplications? = null,
    @param:Json(name = "prior_repayments") val priorRepayments: RepaymentFactListDto? = null,
    @param:Json(name = "unallocated_credit_minor") val unallocatedCreditMinor: Long = 0,
    @param:Json(name = "credit_kind") val creditKind: String? = null,
    val observation: BalanceObservation? = null,
    @param:Json(name = "credit_terms") val creditTerms: CreditTerms? = null,
)

@JsonClass(generateAdapter = true)
data class DebtAdoptionDto(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
)

@JsonClass(generateAdapter = true)
data class CreditPaymentVoidDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "repayment_public_id") val repaymentPublicId: String,
    @param:Json(name = "occurred_on") val occurredOn: String,
    val reason: String,
    @param:Json(name = "reviewed_balance_minor") val reviewedBalanceMinor: Long? = null,
)

@JsonClass(generateAdapter = true)
data class FinancialAccountCreateDto(
    val name: String,
    val kind: String,
    @param:Json(name = "currency_code") val currencyCode: String,
    val visibility: String,
    val institution: String?,
    val tail: String?,
    @param:Json(name = "opening_amount_minor") val openingAmountMinor: Long?,
    @param:Json(name = "opening_date") val openingDate: String,
    @param:Json(name = "opening_source") val openingSource: String,
    @param:Json(name = "credit_terms") val creditTerms: CreditTerms? = null,
    @param:Json(name = "existing_debt") val existingDebt: DebtAdoptionDto? = null,
)

@JsonClass(generateAdapter = true)
data class FinancialAccountEditDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    val name: String, val institution: String?, val tail: String?, val archived: Boolean,
    @param:Json(name = "credit_terms") val creditTerms: CreditTerms? = null,
    val visibility: String? = null,
)

@JsonClass(generateAdapter = true)
data class CreditPaymentDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    @param:Json(name = "calendar_revision") val calendarRevision: Long,
    @param:Json(name = "payer_public_id") val payerPublicId: String,
    @param:Json(name = "payer_row_version") val payerRowVersion: Long,
    @param:Json(name = "principal_minor") val principalMinor: Long,
    @param:Json(name = "payer_amount_minor") val payerAmountMinor: Long,
    @param:Json(name = "occurred_on") val occurredOn: String,
    val note: String,
    @param:Json(name = "new_fee_minor") val newFeeMinor: Long = 0,
    @param:Json(name = "fee_note") val feeNote: String? = null,
    @param:Json(name = "period_allocations") val periodAllocations: List<InstallmentPaymentPartDto> = emptyList(),
    @param:Json(name = "draw_allocations") val drawAllocations: List<CreditDrawPaymentPartDto> = emptyList(),
    @param:Json(name = "overpayment_minor") val overpaymentMinor: Long = 0,
    @param:Json(name = "source_repayment_draft_id") val sourceRepaymentDraftId: String? = null,
    @param:Json(name = "source_amount_basis") val sourceAmountBasis: String = "payer_total",
    @param:Json(name = "source_review_reason") val sourceReviewReason: String? = null,
    @param:Json(name = "fee_payments") val feePayments: List<CreditFeePaymentPartDto> = emptyList(),
    @param:Json(name = "payer_fee_amount_minor") val payerFeeAmountMinor: Long = 0,
)

@JsonClass(generateAdapter = true)
data class ExpenseFundingPartDto(
    @param:Json(name = "component_id") val componentId: String,
    @param:Json(name = "account_public_id") val accountPublicId: String,
    @param:Json(name = "account_row_version") val accountRowVersion: Long,
    @param:Json(name = "expense_amount_minor") val expenseAmountMinor: Long,
    @param:Json(name = "account_amount_minor") val accountAmountMinor: Long,
    @param:Json(name = "included_in_opening") val includedInOpening: Boolean = false,
    @param:Json(name = "expense_currency_code") val expenseCurrencyCode: String? = null,
    @param:Json(name = "account_currency_code") val accountCurrencyCode: String? = null,
)

@JsonClass(generateAdapter = true)
data class ExpenseFundingCommandDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    val parts: List<ExpenseFundingPartDto>, val reason: String,
)

@JsonClass(generateAdapter = true)
data class AccountPostingDto(
    @param:Json(name = "expected_row_version") val expectedRowVersion: Long,
    val kind: String,
    @param:Json(name = "amount_minor") val amountMinor: Long,
    @param:Json(name = "occurred_on") val occurredOn: String,
    val note: String,
    @param:Json(name = "calendar_revision") val calendarRevision: Long,
    @param:Json(name = "other_account_public_id") val otherAccountPublicId: String? = null,
    @param:Json(name = "other_account_row_version") val otherAccountRowVersion: Long? = null,
    @param:Json(name = "other_amount_minor") val otherAmountMinor: Long? = null,
    @param:Json(name = "apply_adjustment") val applyAdjustment: Boolean = false,
    @param:Json(name = "loan_name") val loanName: String? = null,
    @param:Json(name = "loan_currency_code") val loanCurrencyCode: String? = null,
    @param:Json(name = "loan_principal_minor") val loanPrincipalMinor: Long? = null,
)
