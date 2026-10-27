package com.ticketbox.data.repository

internal fun com.ticketbox.data.remote.dto.BillSplitInviteRequestDto.toDomain() = com.ticketbox.domain.model.BillSplitInviteRequest(
    receiverAccountId = receiverAccountId,
    amountCents = amountCents,
    expectedRowVersion = expectedRowVersion,
)

internal fun com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto.toDomain() = com.ticketbox.domain.model.DebtGoalLinksReplaceRequest(
    expectedRowVersion = expectedRowVersion,
    debtPublicIds = debtPublicIds,
)

internal fun com.ticketbox.data.remote.dto.DebtGoalTargetDateRequestDto.toDomain() = com.ticketbox.domain.model.DebtGoalTargetDateRequest(
    expectedRowVersion = expectedRowVersion,
    targetDate = targetDate,
)

internal fun com.ticketbox.data.remote.dto.GoalCreateRequestDto.toDomain() = com.ticketbox.domain.model.GoalCreateRequest(
    name = name,
    goalType = goalType,
    period = period,
    month = month,
    targetAmountCents = targetAmountCents,
    category = category,
    debtPublicIds = debtPublicIds,
    homeCurrencyCode = homeCurrencyCode,
)

internal fun com.ticketbox.data.remote.dto.GoalUpdateRequestDto.toDomain() = com.ticketbox.domain.model.GoalUpdateRequest(
    expectedRowVersion = expectedRowVersion,
    name = name,
    month = month,
    category = category,
    targetAmountCents = targetAmountCents,
    homeCurrencyCode = homeCurrencyCode,
)

internal fun com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto.toDomain() = com.ticketbox.domain.model.IncomePlanUpdateRequest(
    intentMonth = intentMonth,
    expectedRowVersion = expectedRowVersion,
    label = label,
    sourceType = sourceType,
    frequency = frequency,
    incomeMonth = incomeMonth,
    amountCents = amountCents,
    payDay = payDay,
)
