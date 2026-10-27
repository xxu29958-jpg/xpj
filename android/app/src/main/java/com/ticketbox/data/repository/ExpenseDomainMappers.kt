package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.domain.model.ManualExpenseSubmission

internal fun ExpenseManualCreateRequestDto.toDomain(): ManualExpenseSubmission = ManualExpenseSubmission(
    originalCurrency = originalCurrency,
    originalAmount = originalAmount,
    spentAt = spentAt,
    merchant = merchant,
    category = category,
    categoryChoice = categoryChoice,
    note = note,
    expenseTime = expenseTime,
    tags = tags,
    valueScore = valueScore,
    regretScore = regretScore,
    clientRef = clientRef,
    homeCurrencyCode = homeCurrencyCode,
    timeInput = timeInput?.toDomain(),
    funding = funding?.map { it.toDomain() },
)
