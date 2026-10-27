package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.CreditApplicationChoiceDto
import com.ticketbox.data.remote.dto.CreditApplicationHistoryDto
import com.ticketbox.data.remote.dto.CreditApplicationsDto
import com.ticketbox.domain.model.CreditApplicationChoice
import com.ticketbox.domain.model.CreditApplicationHistory
import com.ticketbox.domain.model.CreditApplications

internal fun CreditApplicationChoiceDto.toDomain(): CreditApplicationChoice = CreditApplicationChoice(
    publicId = publicId,
    note = note,
    occurredOn = occurredOn,
    remainingMinor = remainingMinor,
)

internal fun CreditApplicationHistoryDto.toDomain(): CreditApplicationHistory = CreditApplicationHistory(
    publicId = publicId,
    creditNote = creditNote,
    drawNote = drawNote,
    amountMinor = amountMinor,
    appliedMinor = appliedMinor,
    reason = reason,
    createdAt = createdAt,
    voidReason = voidReason,
)

internal fun CreditApplicationsDto.toDomain(): CreditApplications = CreditApplications(
    credits = credits.map { it.toDomain() },
    obligations = obligations.map { it.toDomain() },
    history = history.map { it.toDomain() },
)
