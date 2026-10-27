package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.AccountChoiceDto
import com.ticketbox.data.remote.dto.BalanceObservationDto
import com.ticketbox.data.remote.dto.CreditTermsDto
import com.ticketbox.data.remote.dto.ExistingDebtChoiceDto
import com.ticketbox.data.remote.dto.ExpenseFundingPartDto
import com.ticketbox.data.remote.dto.ExpenseFundingViewDto
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.data.remote.dto.FundMovementDto
import com.ticketbox.data.remote.dto.FundingViewPartDto
import com.ticketbox.data.remote.dto.FundsOverviewDto
import com.ticketbox.domain.model.AccountChoice
import com.ticketbox.domain.model.BalanceObservation
import com.ticketbox.domain.model.CreditTerms
import com.ticketbox.domain.model.ExistingDebtChoice
import com.ticketbox.domain.model.ExpenseFunding
import com.ticketbox.domain.model.ExpenseFundingView
import com.ticketbox.domain.model.FinancialAccount
import com.ticketbox.domain.model.FundMovement
import com.ticketbox.domain.model.FundingViewPart
import com.ticketbox.domain.model.FundsOverview

internal fun AccountChoiceDto.toDomain(): AccountChoice = AccountChoice(
    key = key,
    name = name,
    kind = kind,
    institution = institution,
)

internal fun BalanceObservationDto.toDomain(): BalanceObservation = BalanceObservation(
    observedMinor = observedMinor,
    recordedMinor = recordedMinor,
    differenceMinor = differenceMinor,
    occurredOn = occurredOn,
    source = source,
    adjusted = adjusted,
)

internal fun CreditTermsDto.toDomain(): CreditTerms = CreditTerms(
    creditLimitMinor = creditLimitMinor,
    availableCreditMinor = availableCreditMinor,
    observedOn = observedOn,
    statementDay = statementDay,
    paymentDueDay = paymentDueDay,
    source = source,
)

internal fun CreditTerms.toDto(): CreditTermsDto = CreditTermsDto(
    creditLimitMinor = creditLimitMinor,
    availableCreditMinor = availableCreditMinor,
    observedOn = observedOn,
    statementDay = statementDay,
    paymentDueDay = paymentDueDay,
    source = source,
)

internal fun ExistingDebtChoiceDto.toDomain(): ExistingDebtChoice = ExistingDebtChoice(
    publicId = publicId,
    rowVersion = rowVersion,
    name = name,
    remainingHomeMinor = remainingHomeMinor,
    homeCurrencyCode = homeCurrencyCode,
    earliestOpeningDate = earliestOpeningDate,
)

internal fun ExpenseFundingPartDto.toDomain(): ExpenseFunding = ExpenseFunding(
    componentId = componentId,
    accountPublicId = accountPublicId,
    accountRowVersion = accountRowVersion,
    expenseAmountMinor = expenseAmountMinor,
    accountAmountMinor = accountAmountMinor,
    includedInOpening = includedInOpening,
    expenseCurrencyCode = expenseCurrencyCode,
    accountCurrencyCode = accountCurrencyCode,
)

internal fun ExpenseFundingViewDto.toDomain(): ExpenseFundingView = ExpenseFundingView(
    expenseId = expenseId,
    expenseRowVersion = expenseRowVersion,
    currencyCode = currencyCode,
    totalMinor = totalMinor,
    canEdit = canEdit,
    parts = parts.map { it.toDomain() },
)

internal fun FinancialAccountDto.toDomain(): FinancialAccount = FinancialAccount(
    publicId = publicId,
    name = name,
    ledgerId = ledgerId,
    calendarRevision = calendarRevision,
    kind = kind,
    currencyCode = currencyCode,
    visibility = visibility,
    institution = institution,
    tail = tail,
    rowVersion = rowVersion,
    archived = archived,
    balanceMinor = balanceMinor,
    recordedChangeMinor = recordedChangeMinor,
    openingDate = openingDate,
    openingSource = openingSource,
    debtPublicId = debtPublicId,
    canEdit = canEdit,
    movements = movements.map { it.toDomain() },
    feeObligations = feeObligations.map { it.toDomain() },
    creditApplications = creditApplications?.toDomain(),
    priorRepayments = priorRepayments?.toDomain(),
    unallocatedCreditMinor = unallocatedCreditMinor,
    creditKind = creditKind,
    observation = observation?.toDomain(),
    creditTerms = creditTerms?.toDomain(),
)

internal fun FundMovementDto.toDomain(): FundMovement = FundMovement(
    publicId = publicId,
    eventPublicId = eventPublicId,
    kind = kind,
    amountMinor = amountMinor,
    occurredOn = occurredOn,
    note = note,
    expenseId = expenseId,
    repaymentPublicId = repaymentPublicId,
    canVoidRepayment = canVoidRepayment,
    voided = voided,
    correctionParts = correctionParts.map { it.toDomain() },
)

internal fun FundingViewPartDto.toDomain(): FundingViewPart = FundingViewPart(
    componentId = componentId,
    accountPublicId = accountPublicId,
    accountRowVersion = accountRowVersion,
    accountName = accountName,
    currencyCode = currencyCode,
    expenseAmountMinor = expenseAmountMinor,
    accountAmountMinor = accountAmountMinor,
    includedInOpening = includedInOpening,
)

internal fun FundsOverviewDto.toDomain(): FundsOverview = FundsOverview(
    homeCurrencyCode = homeCurrencyCode,
    valuationDate = valuationDate,
    assetsMinor = assetsMinor,
    liabilitiesMinor = liabilitiesMinor,
    netWorthMinor = netWorthMinor,
    includedAccounts = includedAccounts,
    unknownAccounts = unknownAccounts,
    missingRateAccounts = missingRateAccounts,
)

