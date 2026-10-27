package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import com.ticketbox.domain.model.RecurringOccurrence
import com.ticketbox.domain.model.RecurringOccurrencePaymentRequest

internal fun RecurringOccurrenceDto.toDomain(): RecurringOccurrence = RecurringOccurrence(
    seriesPublicId = seriesPublicId,
    period = period,
    seriesRowVersion = seriesRowVersion,
    rowVersion = rowVersion,
    state = state,
    plannedAmountCents = plannedAmountCents,
    reservedAmountCents = reservedAmountCents,
    expensePublicId = expensePublicId,
    paidAmountCents = paidAmountCents,
    nextDueDate = nextDueDate,
    expenseId = expenseId,
    homeCurrencyCode = homeCurrencyCode,
    paidHomeCurrencyCode = paidHomeCurrencyCode,
    recordedDefinition = recordedDefinition?.toDomain(),
    paymentReviewReason = paymentReviewReason,
)

internal fun RecurringOccurrencePaymentRequestDto.toDomain(): RecurringOccurrencePaymentRequest = RecurringOccurrencePaymentRequest(
    action = action,
    expectedRowVersion = expectedRowVersion,
    expectedSeriesRowVersion = expectedSeriesRowVersion,
    expensePublicId = expensePublicId,
    expectedExpenseRowVersion = expectedExpenseRowVersion,
)

internal fun RecurringOccurrencePaymentRequest.toDto(): RecurringOccurrencePaymentRequestDto = RecurringOccurrencePaymentRequestDto(
    action = action,
    expectedRowVersion = expectedRowVersion,
    expectedSeriesRowVersion = expectedSeriesRowVersion,
    expensePublicId = expensePublicId,
    expectedExpenseRowVersion = expectedExpenseRowVersion,
)
