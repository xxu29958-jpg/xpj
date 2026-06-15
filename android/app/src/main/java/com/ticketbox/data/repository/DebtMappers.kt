package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtSourceTypes

fun DebtDto.toDomain(): Debt = Debt(
    publicId = publicId,
    ledgerId = ledgerId,
    direction = direction,
    counterpartyType = counterpartyType,
    counterpartyAccountId = counterpartyAccountId,
    counterpartyLabel = counterpartyLabel,
    principalAmountCents = principalAmountCents,
    remainingAmountCents = remainingAmountCents,
    paidAmountCents = paidAmountCents,
    status = status,
    sourceType = sourceType,
    sourceId = sourceId,
    homeCurrencyCode = homeCurrencyCode,
    originalCurrencyCode = originalCurrencyCode,
    originalAmountMinor = originalAmountMinor,
    createdAt = createdAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
)

/**
 * A new external Debt to create (ADR-0049 §2). slice 8 captures the home-currency path: a
 * direction, the counterparty's display label, and the home-currency principal in cents.
 */
data class DebtDraft(
    val direction: String,
    val counterpartyLabel: String,
    val principalAmountCents: Long,
)

fun DebtDraft.toCreateRequest(): DebtCreateRequestDto = DebtCreateRequestDto(
    direction = direction,
    // Public create only accepts external/manual; member Debt is server-side (§5.2).
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyLabel = counterpartyLabel.trim(),
    principalAmountCents = principalAmountCents,
    sourceType = DebtSourceTypes.MANUAL,
)
