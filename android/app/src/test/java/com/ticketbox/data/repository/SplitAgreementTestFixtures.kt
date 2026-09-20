package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import com.ticketbox.data.remote.dto.BillSplitChangeProposalDto
import com.ticketbox.data.remote.dto.BillSplitSettlementPreviewDto
import com.ticketbox.data.remote.dto.DebtDto

internal fun splitTestDebt(id: String = "original", version: Long = 7) = DebtDto(
    publicId = id, ledgerId = null, direction = "i_owe", counterpartyType = "member",
    principalAmountCents = 4000, remainingAmountCents = 0, paidAmountCents = 3000,
    status = "cleared", sourceType = "bill_split", sourceId = "invitation", homeCurrencyCode = "CNY",
    createdAt = "2026-09-20T00:00:00Z", updatedAt = "2026-09-20T00:00:00Z", rowVersion = version,
    viewerIsDebtor = false,
)

internal fun splitTestAgreement() = BillSplitAgreementDto(
    invitationPublicId = "invitation", homeCurrencyCode = "CNY", originalShareAmountCents = 4000,
    agreedShareAmountCents = 2000, originalDebt = splitTestDebt(),
    returnDebt = splitTestDebt("return", 8).copy(direction = "owed_to_me", sourceType = "bill_split_return"),
    viewerIsParty = true, originalPaidAmountCents = 3000, returnPaidAmountCents = 0,
    originalForgivenAmountCents = 1000, returnForgivenAmountCents = 0, settlementNetAmountCents = -1000,
    preview = BillSplitSettlementPreviewDto(2000, -1000, -1000, true),
)

internal fun splitTestProposal() = BillSplitChangeProposalDto(
    publicId = "proposal", originalDebtPublicId = "original", returnDebtPublicId = "return", status = "pending",
    proposedByYou = false, shareBeforeAmountCents = 4000, newShareAmountCents = 2000,
    settlementBeforeNetAmountCents = 0, settlementNetAmountCents = -1000,
    originalPaidAmountCents = 3000, returnPaidAmountCents = 0, originalForgivenAmountCents = 1000,
    returnForgivenAmountCents = 0, originalDebtRowVersion = 7, returnDebtRowVersion = 8, reason = "退款后重议",
    createdAt = "2026-09-20T00:00:00Z", expiresAt = "2026-09-27T00:00:00Z",
)
