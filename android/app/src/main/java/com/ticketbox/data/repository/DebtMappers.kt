package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtBillParseResponseDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalDto
import com.ticketbox.data.remote.dto.RepaymentCreateResponseDto
import com.ticketbox.data.remote.dto.RepaymentFactDto
import com.ticketbox.data.remote.dto.RepaymentFactListResponseDto
import com.ticketbox.data.remote.dto.RepaymentVoidFactDto
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtKinds
import com.ticketbox.domain.model.DebtRepaymentFact
import com.ticketbox.domain.model.DebtRepaymentHistory
import com.ticketbox.domain.model.DebtRepaymentRecord
import com.ticketbox.domain.model.DebtRepaymentVoidFact
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
    homeCurrencyCode = supportedCurrencyCode(homeCurrencyCode),
    originalCurrencyCode = originalCurrencyCode?.let(::supportedCurrencyCode),
    originalAmountMinor = originalAmountMinor,
    createdAt = createdAt,
    updatedAt = updatedAt,
    rowVersion = rowVersion,
    viewerIsDebtor = viewerIsDebtor,
    isForgiven = isForgiven,
)

fun RepaymentCreateResponseDto.toDomain(amountCents: Long): DebtRepaymentFact = DebtRepaymentFact(
    publicId = repaymentPublicId,
    amountCents = amountCents,
    debt = Debt(
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
        homeCurrencyCode = supportedCurrencyCode(homeCurrencyCode),
        originalCurrencyCode = originalCurrencyCode?.let(::supportedCurrencyCode),
        originalAmountMinor = originalAmountMinor,
        createdAt = createdAt,
        updatedAt = updatedAt,
        rowVersion = rowVersion,
        viewerIsDebtor = viewerIsDebtor,
        isForgiven = isForgiven,
    ),
)

fun RepaymentFactListResponseDto.toDomain(): DebtRepaymentHistory = DebtRepaymentHistory(
    debtPublicId = debtPublicId,
    homeCurrencyCode = supportedCurrencyCode(homeCurrencyCode),
    items = items.map { it.toDomain() },
    page = page,
    pageSize = pageSize,
    total = total,
)

private fun RepaymentFactDto.toDomain(): DebtRepaymentRecord = DebtRepaymentRecord(
    publicId = publicId,
    amountCents = amountCents,
    originalCurrencyCode = originalCurrencyCode?.let(::supportedCurrencyCode),
    originalAmountMinor = originalAmountMinor,
    exchangeRateToCny = exchangeRateToCny,
    exchangeRateDate = exchangeRateDate,
    exchangeRateSource = exchangeRateSource,
    paidAt = paidAt,
    createdAt = createdAt,
    status = status,
    voidFact = voidFact?.toDomain(),
)

private fun RepaymentVoidFactDto.toDomain(): DebtRepaymentVoidFact = DebtRepaymentVoidFact(
    publicId = publicId,
    reason = reason,
    createdAt = createdAt,
)

fun DebtBillParseResponseDto.toDomain(): DebtBillSuggestion = DebtBillSuggestion(
    merchant = merchant,
    principalAmountCents = principalAmountCents,
    installmentCount = installmentCount,
    installmentPeriodMonths = installmentPeriodMonths,
    perPeriodAmountCents = perPeriodAmountCents,
    repaymentDay = repaymentDay,
    sourceText = sourceText,
    confidence = confidence,
)

/**
 * A new external Debt to create (ADR-0049 §2). slice 8 captures the home-currency path: a
 * direction, the counterparty's display label, and the home-currency principal in cents.
 * [debtKind] (8e-6e) is the optional repayment-rhythm classification the create form's picker sets;
 * it defaults to [DebtKinds.UNSPECIFIED] so a form that doesn't touch it still creates a Debt.
 * [installmentCount] / [installmentPeriodMonths] (§B) are the optional 分期期数 / 还款周期 — meaningful
 * ONLY when [debtKind] is installment (the create form shows them only then); [toCreateRequest] drops
 * them for any other kind so a stale value from a kind the user later switched away from can't reach
 * the backend (which 422s 期数 on a non-installment debt). [installmentPeriodMonths] null → the backend
 * defaults the period to monthly (每月一期 = the cold-start default); it only rides along WITH a count
 * (the backend CHECK pairs the two).
 */
data class DebtDraft(
    val direction: String,
    val counterpartyLabel: String,
    val principalAmountCents: Long,
    val debtKind: String = DebtKinds.UNSPECIFIED,
    val installmentCount: Int? = null,
    val installmentPeriodMonths: Int? = null,
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
    // 周期同 gate，且只在 count 也给时随车（后端 CHECK 把 count/period 配对；period 留空→后端默认每月）。
    installmentPeriodMonths = installmentPeriodMonths
        ?.takeIf { debtKind == DebtKinds.INSTALLMENT && installmentCount != null }?.toLong(),
)

/** ADR-0049 §3.2 (slice 8d) — map a member repayment proposal DTO to its domain model. */
fun MemberRepaymentProposalDto.toDomain(): MemberRepaymentProposal = MemberRepaymentProposal(
    publicId = publicId,
    debtPublicId = debtPublicId,
    status = status,
    proposedAmountCents = proposedAmountCents,
    confirmedAmountCents = confirmedAmountCents,
    homeCurrencyCode = supportedCurrencyCode(homeCurrencyCode),
    originalCurrencyCode = originalCurrencyCode?.let(::supportedCurrencyCode),
    originalAmountMinor = originalAmountMinor,
    paidAt = paidAt,
    note = note,
    expiresAt = expiresAt,
    createdAt = createdAt,
    resolvedAt = resolvedAt,
    supersedesProposalPublicId = supersedesProposalPublicId,
    committedRepaymentPublicId = committedRepaymentPublicId,
)

private fun supportedCurrencyCode(value: String): String =
    CurrencyCode.requireSupported(value).storageKey
