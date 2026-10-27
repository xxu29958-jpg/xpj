package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseFundingPartDto
import com.ticketbox.data.remote.dto.FinancialAccountDto
import com.ticketbox.domain.model.ExpenseFunding
import com.ticketbox.domain.model.FinancialAccount

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
    movements = movements,
    feeObligations = feeObligations,
    creditApplications = creditApplications,
    priorRepayments = priorRepayments?.toDomain(),
    unallocatedCreditMinor = unallocatedCreditMinor,
    creditKind = creditKind,
    observation = observation,
    creditTerms = creditTerms,
)
