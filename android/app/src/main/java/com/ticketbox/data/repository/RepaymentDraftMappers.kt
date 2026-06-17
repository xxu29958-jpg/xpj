package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import com.ticketbox.domain.model.RepaymentDraft
import com.ticketbox.domain.model.RepaymentNotificationDraft

/** ADR-0049 §杠杆③ (slice 3a) — map a repayment-draft DTO to its domain inbox model. */
fun RepaymentDraftDto.toDomain(): RepaymentDraft = RepaymentDraft(
    publicId = publicId,
    source = source,
    amountCents = amountCents,
    homeCurrencyCode = homeCurrencyCode,
    merchantLabel = merchantLabel,
    capturedAt = capturedAt,
    status = status,
    suggestedDebtPublicId = suggestedDebtPublicId,
    committedDebtPublicId = committedDebtPublicId,
    committedRepaymentPublicId = committedRepaymentPublicId,
    createdAt = createdAt,
    resolvedAt = resolvedAt,
)

/** The NLS-captured repayment as a create-request body (home-currency only; §杠杆③). */
fun RepaymentNotificationDraft.toCreateRequest(notificationKey: String?): RepaymentDraftCreateRequestDto =
    RepaymentDraftCreateRequestDto(
        source = source.apiValue,
        amountCents = amountCents,
        merchantLabel = merchantLabel?.trim()?.ifBlank { null },
        capturedAt = capturedAt,
        notificationKey = notificationKey,
    )

/** Confirm body — pay the captured repayment down against the chosen Debt under its OCC token. */
fun confirmRepaymentDraftRequest(
    targetDebtPublicId: String,
    expectedRowVersion: Long,
): RepaymentDraftConfirmRequestDto = RepaymentDraftConfirmRequestDto(
    targetDebtPublicId = targetDebtPublicId,
    expectedRowVersion = expectedRowVersion,
)
