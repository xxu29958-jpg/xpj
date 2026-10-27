package com.ticketbox.data.repository

internal fun com.ticketbox.data.remote.dto.DebtAdjustmentCreateRequestDto.toDomain() = com.ticketbox.domain.model.DebtAdjustmentCreateRequest(
    amountCents = amountCents,
    reason = reason,
    expectedRowVersion = expectedRowVersion,
)

internal fun com.ticketbox.data.remote.dto.DebtKindSetRequestDto.toDomain() = com.ticketbox.domain.model.DebtKindSetRequest(
    debtKind = debtKind,
    expectedRowVersion = expectedRowVersion,
)

internal fun com.ticketbox.data.remote.dto.DebtVoidCreateRequestDto.toDomain() = com.ticketbox.domain.model.DebtVoidCreateRequest(
    reason = reason,
    expectedRowVersion = expectedRowVersion,
)

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

internal fun com.ticketbox.data.remote.dto.RepaymentVoidCreateRequestDto.toDomain() = com.ticketbox.domain.model.RepaymentVoidCreateRequest(
    repaymentPublicId = repaymentPublicId,
    reason = reason,
    expectedRowVersion = expectedRowVersion,
)
