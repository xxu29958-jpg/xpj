package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.CorrectionOptionalInt
import com.ticketbox.data.remote.dto.CorrectionOptionalString
import com.ticketbox.data.remote.dto.CorrectionOptionalTimeInput
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.domain.model.CorrectionIntChange
import com.ticketbox.domain.model.CorrectionStringChange
import com.ticketbox.domain.model.CorrectionTimeChange
import com.ticketbox.domain.model.ExpenseCorrectionSubmission

internal fun CorrectionOptionalInt.toDomain(): CorrectionIntChange = CorrectionIntChange(
    changed = changed,
    value = value,
)

internal fun CorrectionOptionalString.toDomain(): CorrectionStringChange = CorrectionStringChange(
    changed = changed,
    value = value,
)

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
    expenseTime = expenseTime.toDomain(),
    tags = tags,
    valueScore = valueScore.toDomain(),
    regretScore = regretScore.toDomain(),
    items = items?.map { it.toDomain() },
    splits = splits?.map { it.toDomain() },
    timeInput = timeInput.toDomain(),
)
