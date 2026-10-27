package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import com.ticketbox.domain.model.BillSplitAgreement

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
    pendingProposal = pendingProposal,
    preview = preview,
)
