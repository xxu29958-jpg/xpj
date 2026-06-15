package com.ticketbox.domain.model

/**
 * ADR-0049 §3.2 (slice 8d) MemberRepaymentProposal domain model.
 *
 * For a `counterparty_type='member'` [Debt] the debtor cannot directly commit a repayment (that
 * would unilaterally reduce the creditor's receivable, §5.2). Instead the debtor *proposes* "I
 * paid" — a pending intent that does NOT touch the §2 fold — and the creditor confirms (full or
 * partial), rejects, or the debtor withdraws while it is still pending. The raw backend status
 * string is kept as `String` and mapped to a localized label in the UI layer (mirroring the
 * BillSplit / DebtGoal pattern); the canonical values are pinned by [MemberProposalStatuses] so
 * branching never hardcodes literals. All amounts are home-currency minor units (cents);
 * `proposed`/`confirmed` are server-frozen (§2.2) and never recomputed on the client.
 */
object MemberProposalStatuses {
    const val PENDING = "pending"
    const val CONFIRMED = "confirmed"
    const val PARTIALLY_CONFIRMED = "partially_confirmed"
    const val REJECTED = "rejected"
    const val WITHDRAWN = "withdrawn"
    const val EXPIRED = "expired"
    const val SUPERSEDED = "superseded"
}

data class MemberRepaymentProposal(
    val publicId: String,
    val debtPublicId: String,
    val status: String,
    val proposedAmountCents: Long,
    val confirmedAmountCents: Long?,
    val homeCurrencyCode: String,
    val originalCurrencyCode: String?,
    val originalAmountMinor: Long?,
    val paidAt: String,
    val note: String?,
    val expiresAt: String,
    val createdAt: String,
    val resolvedAt: String?,
    val supersedesProposalPublicId: String?,
    val committedRepaymentPublicId: String?,
) {
    /** Still awaiting the creditor: the only state the debtor may withdraw or the creditor act on. */
    val isPending: Boolean get() = status == MemberProposalStatuses.PENDING
    val isConfirmed: Boolean get() = status == MemberProposalStatuses.CONFIRMED
    val isPartiallyConfirmed: Boolean get() = status == MemberProposalStatuses.PARTIALLY_CONFIRMED

    /** A confirm committed a repayment (full or partial) — the amount actually accepted. */
    val isResolvedByConfirm: Boolean get() = isConfirmed || isPartiallyConfirmed
}
