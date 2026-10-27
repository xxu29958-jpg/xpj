package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BudgetAdviceInputsDto
import com.ticketbox.data.remote.dto.MissingExchangeRateDto
import com.ticketbox.domain.model.MonthlyArrangement
import com.ticketbox.domain.model.BudgetAdviceBreakdown
import com.ticketbox.domain.model.BudgetAdviceDataScope
import com.ticketbox.domain.model.BudgetAdviceInputs
import com.ticketbox.domain.model.BudgetPlanDefinition
import com.ticketbox.domain.model.CurrencyProjectionGap

fun BudgetAdviceInputsDto.toDomain() = BudgetAdviceInputs(
    month = month,
    homeCurrencyCode = homeCurrencyCode,
    breakdown = breakdown.let { BudgetAdviceBreakdown(it.monthlyIncomeCents, it.fixedExpensesCents,
        it.spentAmountCents, it.savingsTargetCents, it.reservedBufferCents, it.discretionaryCents, it.shortfallCents) },
    missingRates = missingRates.map { it.toDomain() },
    referenceRates = referenceRates.map { it.toDomain() },
    inputsFingerprint = inputsFingerprint,
    undatedExpenseCount = undatedExpenseCount,
    savedArrangement = savedArrangement?.toDomain(),
    isTrial = isTrial,
    arrangementCurrencyCode = arrangementCurrencyCode,
    budgetDefinition = budgetDefinition?.let { BudgetPlanDefinition(it.homeCurrencyCode, it.totalAmountCents,
        it.nonMonthlyAmountCents, it.rolloverAmountCents, it.excludedCategories, it.rowVersion, it.updatedAt) },
    plannedTotalCents = plannedTotalCents,
    dataScope = dataScope?.let { BudgetAdviceDataScope(it.readAt, it.historyFromMonth, it.historyToMonth, it.historyCategoryCount) },
)

fun MissingExchangeRateDto.toDomain() = CurrencyProjectionGap(sourceCurrencyCode, homeCurrencyCode, rateDate)

internal fun CurrencyProjectionGap.toDto() = MissingExchangeRateDto(sourceCurrencyCode, homeCurrencyCode, rateDate)
