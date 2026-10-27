package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import com.ticketbox.data.remote.dto.BillSplitChangeAcceptRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeCreateRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeProposalDto
import com.ticketbox.data.remote.dto.BillSplitSettlementPreviewDto
import com.ticketbox.domain.model.BillSplitAgreement
import com.ticketbox.domain.model.BillSplitChangeAcceptRequest
import com.ticketbox.domain.model.BillSplitChangeCreateRequest
import com.ticketbox.domain.model.BillSplitChangeProposal
import com.ticketbox.domain.model.BillSplitSettlementPreview

internal fun BillSplitAgreementDto.toDomain(): BillSplitAgreement = BillSplitAgreement(
    invitationPublicId = invitationPublicId,
    homeCurrencyCode = homeCurrencyCode,
    originalShareAmountCents = originalShareAmountCents,
    agreedShareAmountCents = agreedShareAmountCents,
    originalDebt = originalDebt.toDomain(),
    returnDebt = returnDebt?.toDomain(),
    viewerIsParty = viewerIsParty,
    originalPaidAmountCents = originalPaidAmountCents,
    returnPaidAmountCents = returnPaidAmountCents,
    originalForgivenAmountCents = originalForgivenAmountCents,
    returnForgivenAmountCents = returnForgivenAmountCents,
    settlementNetAmountCents = settlementNetAmountCents,
    pendingRepaymentDebtPublicIds = pendingRepaymentDebtPublicIds,
    pendingProposal = pendingProposal?.toDomain(),
    preview = preview.toDomain(),
)

internal fun BillSplitChangeAcceptRequestDto.toDomain(): BillSplitChangeAcceptRequest = BillSplitChangeAcceptRequest(
    expectedRowVersion = expectedRowVersion,
    expectedReturnRowVersion = expectedReturnRowVersion,
)

internal fun BillSplitChangeAcceptRequest.toDto(): BillSplitChangeAcceptRequestDto = BillSplitChangeAcceptRequestDto(
    expectedRowVersion = expectedRowVersion,
    expectedReturnRowVersion = expectedReturnRowVersion,
)

internal fun BillSplitChangeCreateRequestDto.toDomain(): BillSplitChangeCreateRequest = BillSplitChangeCreateRequest(
    newShareAmountCents = newShareAmountCents,
    settlementNetAmountCents = settlementNetAmountCents,
    reason = reason,
    expectedRowVersion = expectedRowVersion,
    expectedReturnRowVersion = expectedReturnRowVersion,
    supersedesProposalPublicId = supersedesProposalPublicId,
)

internal fun BillSplitChangeCreateRequest.toDto(): BillSplitChangeCreateRequestDto = BillSplitChangeCreateRequestDto(
    newShareAmountCents = newShareAmountCents,
    settlementNetAmountCents = settlementNetAmountCents,
    reason = reason,
    expectedRowVersion = expectedRowVersion,
    expectedReturnRowVersion = expectedReturnRowVersion,
    supersedesProposalPublicId = supersedesProposalPublicId,
)

internal fun BillSplitChangeProposalDto.toDomain(): BillSplitChangeProposal = BillSplitChangeProposal(
    publicId = publicId,
    originalDebtPublicId = originalDebtPublicId,
    returnDebtPublicId = returnDebtPublicId,
    status = status,
    proposedByYou = proposedByYou,
    shareBeforeAmountCents = shareBeforeAmountCents,
    newShareAmountCents = newShareAmountCents,
    settlementBeforeNetAmountCents = settlementBeforeNetAmountCents,
    settlementNetAmountCents = settlementNetAmountCents,
    originalPaidAmountCents = originalPaidAmountCents,
    returnPaidAmountCents = returnPaidAmountCents,
    originalForgivenAmountCents = originalForgivenAmountCents,
    returnForgivenAmountCents = returnForgivenAmountCents,
    originalDebtRowVersion = originalDebtRowVersion,
    returnDebtRowVersion = returnDebtRowVersion,
    reason = reason,
    createdAt = createdAt,
    expiresAt = expiresAt,
    resolvedAt = resolvedAt,
)

internal fun BillSplitSettlementPreviewDto.toDomain(): BillSplitSettlementPreview = BillSplitSettlementPreview(
    newShareAmountCents = newShareAmountCents,
    defaultSettlementNetAmountCents = defaultSettlementNetAmountCents,
    cashBasedSettlementNetAmountCents = cashBasedSettlementNetAmountCents,
    requiresExplicitSettlement = requiresExplicitSettlement,
)
