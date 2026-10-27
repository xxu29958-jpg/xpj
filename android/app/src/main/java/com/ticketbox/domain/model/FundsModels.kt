package com.ticketbox.domain.model

/** Values consumed by the product; wire names and persistence remain at the repository boundary. */
data class AccountChoice(
    val key: String, val name: String, val kind: String, val institution: String
)

data class BalanceObservation(
    val observedMinor: Long,
    val recordedMinor: Long,
    val differenceMinor: Long,
    val occurredOn: String,
    val source: String, val adjusted: Boolean,
)

data class CreditTerms(
    val creditLimitMinor: Long? = null,
    val availableCreditMinor: Long? = null,
    val observedOn: String? = null,
    val statementDay: Int? = null,
    val paymentDueDay: Int? = null,
    val source: String? = null,
)

data class ExistingDebtChoice(
    val publicId: String,
    val rowVersion: Long,
    val name: String,
    val remainingHomeMinor: Long,
    val homeCurrencyCode: String,
    val earliestOpeningDate: String,
)

data class ExpenseFundingView(
    val expenseId: Long,
    val expenseRowVersion: Long,
    val currencyCode: String,
    val totalMinor: Long?,
    val canEdit: Boolean,
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

data class FundMovement(
    val publicId: String,
    val eventPublicId: String,
    val kind: String,
    val amountMinor: Long,
    val occurredOn: String,
    val note: String,
    val expenseId: Long?,
    val repaymentPublicId: String?,
    val canVoidRepayment: Boolean = false,
    val voided: Boolean = false,
    val correctionParts: List<ActivityCorrectionPart> = emptyList(),
)

data class FundingViewPart(
    val componentId: String,
    val accountPublicId: String?,
    val accountRowVersion: Long?,
    val accountName: String,
    val currencyCode: String?,
    val expenseAmountMinor: Long,
    val accountAmountMinor: Long?,
    val includedInOpening: Boolean,
)

data class FundsOverview(
    val homeCurrencyCode: String,
    val valuationDate: String,
    val assetsMinor: Long,
    val liabilitiesMinor: Long,
    val netWorthMinor: Long,
    val includedAccounts: Int,
    val unknownAccounts: Int,
    val missingRateAccounts: Int,
)
