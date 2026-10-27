package com.ticketbox.data.repository

internal fun com.ticketbox.data.local.RepaymentReviewInputEntity.toDomain() = com.ticketbox.domain.model.RepaymentReviewInput(
    ownerKey = ownerKey,
    ledgerId = ledgerId,
    draftPublicId = draftPublicId,
    serverUrl = serverUrl,
    sessionGeneration = sessionGeneration,
    bindingRevision = bindingRevision,
    originalKey = originalKey,
    currency = currency,
    amountText = amountText,
    debtPublicId = debtPublicId,
    debtLabel = debtLabel,
    debtHomeCurrency = debtHomeCurrency,
    debtRowVersion = debtRowVersion,
    submittedAction = submittedAction,
    paymentDate = paymentDate,
    calendarRevision = calendarRevision,
    targetChoiceExplicit = targetChoiceExplicit,
)
