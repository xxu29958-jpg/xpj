package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalDto
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtKinds
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
    debtKind = debtKind,
    installmentCount = installmentCount,
    installmentPeriodMonths = installmentPeriodMonths,
    installmentPayoffDate = installmentPayoffDate,
    installmentPaidCount = installmentPaidCount,
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
 * [debtKind] (8e-6e) is the optional repayment-rhythm classification the create form's picker sets;
 * it defaults to [DebtKinds.UNSPECIFIED] so a form that doesn't touch it still creates a Debt.
 * [installmentCount] (§B) is the optional 分期期数 — meaningful ONLY when [debtKind] is installment
 * (the create form shows it only then); [toCreateRequest] drops it for any other kind so a stale
 * value from a kind the user later switched away from can't reach the backend (which 422s 期数 on a
 * non-installment debt). 周期 (period) is not captured here — the backend defaults it to monthly.
 */
data class DebtDraft(
    val direction: String,
    val counterpartyLabel: String,
    val principalAmountCents: Long,
    val debtKind: String = DebtKinds.UNSPECIFIED,
    val installmentCount: Int? = null,
)

fun DebtDraft.toCreateRequest(): DebtCreateRequestDto = DebtCreateRequestDto(
    direction = direction,
    // Public create only accepts external/manual; member Debt is server-side (§5.2).
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyLabel = counterpartyLabel.trim(),
    principalAmountCents = principalAmountCents,
    sourceType = DebtSourceTypes.MANUAL,
    debtKind = debtKind,
    // §B chokepoint: 期数 only rides along for an installment debt. The backend pairs 期数 with
    // kind=='installment' (a non-installment 期数 → 422 "分期期数信息不正确"); gating here means the
    // create form needn't clear the field when the user toggles kind away from installment.
    installmentCount = installmentCount?.takeIf { debtKind == DebtKinds.INSTALLMENT }?.toLong(),
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
