package com.ticketbox.domain.model

import com.squareup.moshi.Json
import com.squareup.moshi.JsonClass

@JsonClass(generateAdapter = true)
data class AccountChoice(val key: String, val name: String, val kind: String, val institution: String)

@JsonClass(generateAdapter = true)
data class BalanceObservation(
    @param:Json(name = "observed_minor") val observedMinor: Long,
    @param:Json(name = "recorded_minor") val recordedMinor: Long,
    @param:Json(name = "difference_minor") val differenceMinor: Long,
    @param:Json(name = "occurred_on") val occurredOn: String,
    val source: String, val adjusted: Boolean,
)

@JsonClass(generateAdapter = true)
data class CreditTerms(
    @param:Json(name = "credit_limit_minor") val creditLimitMinor: Long? = null,
    @param:Json(name = "available_credit_minor") val availableCreditMinor: Long? = null,
    @param:Json(name = "observed_on") val observedOn: String? = null,
    @param:Json(name = "statement_day") val statementDay: Int? = null,
    @param:Json(name = "payment_due_day") val paymentDueDay: Int? = null,
    val source: String? = null,
)

@JsonClass(generateAdapter = true)
data class ExistingDebtChoice(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "row_version") val rowVersion: Long,
    val name: String,
    @param:Json(name = "remaining_home_minor") val remainingHomeMinor: Long,
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "earliest_opening_date") val earliestOpeningDate: String,
)

@JsonClass(generateAdapter = true)
data class ExpenseFundingView(
    @param:Json(name = "expense_id") val expenseId: Long,
    @param:Json(name = "expense_row_version") val expenseRowVersion: Long,
    @param:Json(name = "currency_code") val currencyCode: String,
    @param:Json(name = "total_minor") val totalMinor: Long?,
    @param:Json(name = "can_edit") val canEdit: Boolean,
    val parts: List<FundingViewPart>,
)

data class FinancialAccount(
    val publicId: String,
    val name: String,
    val ledgerId: String,
    val calendarRevision: Long,
    val kind: String,
    val currencyCode: String,
    val visibility: String,
    val institution: String?,
    val tail: String?,
    val rowVersion: Long,
    val archived: Boolean,
    val balanceMinor: Long?,
    val recordedChangeMinor: Long,
    val openingDate: String,
    val openingSource: String,
    val debtPublicId: String?,
    val canEdit: Boolean,
    val movements: List<FundMovement> = emptyList(),
    val feeObligations: List<CreditFeeView> = emptyList(),
    val creditApplications: CreditApplications? = null,
    val priorRepayments: RepaymentFactList? = null,
    val unallocatedCreditMinor: Long = 0,
    val creditKind: String? = null,
    val observation: BalanceObservation? = null,
    val creditTerms: CreditTerms? = null,
)

@JsonClass(generateAdapter = true)
data class FundMovement(
    @param:Json(name = "public_id") val publicId: String,
    @param:Json(name = "event_public_id") val eventPublicId: String,
    val kind: String,
    @param:Json(name = "amount_minor") val amountMinor: Long,
    @param:Json(name = "occurred_on") val occurredOn: String,
    val note: String,
    @param:Json(name = "expense_id") val expenseId: Long?,
    @param:Json(name = "repayment_public_id") val repaymentPublicId: String?,
    @param:Json(name = "can_void_repayment") val canVoidRepayment: Boolean = false,
    val voided: Boolean = false,
    @param:Json(name = "correction_parts") val correctionParts: List<ActivityCorrectionPart> = emptyList(),
)

@JsonClass(generateAdapter = true)
data class FundingViewPart(
    @param:Json(name = "component_id") val componentId: String,
    @param:Json(name = "account_public_id") val accountPublicId: String?,
    @param:Json(name = "account_row_version") val accountRowVersion: Long?,
    @param:Json(name = "account_name") val accountName: String,
    @param:Json(name = "currency_code") val currencyCode: String?,
    @param:Json(name = "expense_amount_minor") val expenseAmountMinor: Long,
    @param:Json(name = "account_amount_minor") val accountAmountMinor: Long?,
    @param:Json(name = "included_in_opening") val includedInOpening: Boolean,
)

@JsonClass(generateAdapter = true)
data class FundsOverview(
    @param:Json(name = "home_currency_code") val homeCurrencyCode: String,
    @param:Json(name = "valuation_date") val valuationDate: String,
    @param:Json(name = "assets_minor") val assetsMinor: Long,
    @param:Json(name = "liabilities_minor") val liabilitiesMinor: Long,
    @param:Json(name = "net_worth_minor") val netWorthMinor: Long,
    @param:Json(name = "included_accounts") val includedAccounts: Int,
    @param:Json(name = "unknown_accounts") val unknownAccounts: Int,
    @param:Json(name = "missing_rate_accounts") val missingRateAccounts: Int,
)
