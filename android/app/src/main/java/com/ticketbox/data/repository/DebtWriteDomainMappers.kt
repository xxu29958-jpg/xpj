package com.ticketbox.data.repository

internal fun com.ticketbox.data.remote.dto.RepaymentCreateRequestDto.toDomain() = com.ticketbox.domain.model.RepaymentCreateRequest(
    amountCents = amountCents,
    expectedRowVersion = expectedRowVersion,
    paidAt = paidAt,
    timeInput = timeInput?.toDomain(),
)

internal fun com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto.toDomain() = com.ticketbox.domain.model.RepaymentDraftConfirmRequest(
    targetDebtPublicId = targetDebtPublicId,
    expectedRowVersion = expectedRowVersion,
    originalCurrency = originalCurrency,
    originalAmount = originalAmount,
    timeInput = timeInput?.toDomain(),
    targetChoiceExplicit = targetChoiceExplicit,
)
