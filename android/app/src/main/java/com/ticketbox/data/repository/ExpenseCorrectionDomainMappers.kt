package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.CorrectionOptionalTimeInput
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.domain.model.CorrectionTimeChange
import com.ticketbox.domain.model.ExpenseCorrectionSubmission

internal fun CorrectionOptionalTimeInput.toDomain(): CorrectionTimeChange = CorrectionTimeChange(
    changed = changed,
    value = value?.toDomain(),
)

internal fun ExpenseCorrectionRequestDto.toDomain(): ExpenseCorrectionSubmission = ExpenseCorrectionSubmission(
    expectedRowVersion = expectedRowVersion,
    reason = reason,
    amountCents = amountCents,
    originalCurrencyCode = originalCurrencyCode,
    originalAmountMinor = originalAmountMinor,
    merchant = merchant,
    category = category,
    categoryChoice = categoryChoice,
    note = note,
    expenseTime = expenseTime,
    tags = tags,
    valueScore = valueScore,
    regretScore = regretScore,
    items = items?.map { it.toDomain() },
    splits = splits?.map { it.toDomain() },
    timeInput = timeInput.toDomain(),
)
