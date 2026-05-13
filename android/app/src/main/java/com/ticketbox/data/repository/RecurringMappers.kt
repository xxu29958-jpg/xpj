package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem

fun RecurringItemDto.toDomain(): RecurringItem = RecurringItem(
    publicId = publicId,
    ledgerId = ledgerId,
    merchant = merchant,
    merchantKey = merchantKey,
    frequency = frequency,
    baselineAmountCents = baselineAmountCents,
    lastAmountCents = lastAmountCents,
    occurrenceCount = occurrenceCount,
    lastSeenAt = lastSeenAt,
    nextExpectedDate = nextExpectedDate,
    status = status,
    confidence = confidence,
    source = source,
    anomalyStatus = anomalyStatus,
    currentMonthAmountCents = currentMonthAmountCents,
    historicalAverageAmountCents = historicalAverageAmountCents,
    amountDeltaPercent = amountDeltaPercent,
    createdAt = createdAt,
    updatedAt = updatedAt,
    pausedAt = pausedAt,
    archivedAt = archivedAt,
)

fun RecurringCandidate.toConfirmRequest(nextExpectedDate: String? = null): RecurringCandidateConfirmRequestDto =
    RecurringCandidateConfirmRequestDto(
        merchant = merchant,
        amountCents = amountCents,
        occurrenceCount = occurrenceCount,
        lastSeenAt = lastSeenAt,
        confidence = confidence,
        frequency = "monthly",
        nextExpectedDate = nextExpectedDate,
    )
