package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalDto
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.MemberRepaymentProposal

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
    viewerIsDebtor = viewerIsDebtor,
    isForgiven = isForgiven,
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

/** ADR-0049 §3.2 (slice 8d) — map a member repayment proposal DTO to its domain model. */
fun MemberRepaymentProposalDto.toDomain(): MemberRepaymentProposal = MemberRepaymentProposal(
    publicId = publicId,
    debtPublicId = debtPublicId,
    status = status,
    proposedAmountCents = proposedAmountCents,
    confirmedAmountCents = confirmedAmountCents,
    homeCurrencyCode = homeCurrencyCode,
    originalCurrencyCode = originalCurrencyCode,
    originalAmountMinor = originalAmountMinor,
    paidAt = paidAt,
    note = note,
    expiresAt = expiresAt,
    createdAt = createdAt,
    resolvedAt = resolvedAt,
    supersedesProposalPublicId = supersedesProposalPublicId,
    committedRepaymentPublicId = committedRepaymentPublicId,
)
