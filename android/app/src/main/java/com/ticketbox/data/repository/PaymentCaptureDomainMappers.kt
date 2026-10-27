package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.PaymentCandidateDto
import com.ticketbox.data.remote.dto.PaymentCaptureDecisionDto
import com.ticketbox.data.remote.dto.PaymentCaptureDto
import com.ticketbox.domain.model.PaymentCandidate
import com.ticketbox.domain.model.PaymentCapture
import com.ticketbox.domain.model.PaymentCaptureDecision

internal fun PaymentCandidateDto.toDomain(): PaymentCandidate = PaymentCandidate(
    kind = kind,
    amountMinor = amountMinor,
    field = field,
    evidence = evidence,
)

internal fun PaymentCaptureDecisionDto.toDomain(): PaymentCaptureDecision = PaymentCaptureDecision(
    expectedRowVersion = expectedRowVersion,
    kind = kind,
    originalCurrency = originalCurrency,
    originalAmountMinor = originalAmountMinor,
    merchant = merchant,
    reason = reason,
)

internal fun PaymentCaptureDecision.toDto(): PaymentCaptureDecisionDto = PaymentCaptureDecisionDto(
    expectedRowVersion = expectedRowVersion,
    kind = kind,
    originalCurrency = originalCurrency,
    originalAmountMinor = originalAmountMinor,
    merchant = merchant,
    reason = reason,
)

internal fun PaymentCaptureDto.toDomain(): PaymentCapture = PaymentCapture(
    publicId = publicId,
    rowVersion = rowVersion,
    source = source,
    capturedAt = capturedAt,
    originalCurrency = originalCurrency,
    originalAmountMinor = originalAmountMinor,
    merchant = merchant,
    kind = kind,
    parserVersion = parserVersion,
    candidates = candidates.map { it.toDomain() },
    expenseId = expenseId,
    expensePublicId = expensePublicId,
    repaymentPublicId = repaymentPublicId,
    recognitionTime = recognitionTime?.toDomain(),
)
