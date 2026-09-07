package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtProposalActions
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.MemberProposalStatuses
import com.ticketbox.domain.model.MemberRepaymentProposal
import kotlinx.coroutines.CompletableDeferred

internal data class ProposalCreateCall(
    val debtPublicId: String,
    val proposedAmountCents: Long,
    val note: String?,
    val supersedesProposalPublicId: String?,
)

internal data class ProposalConfirmCall(
    val debtPublicId: String,
    val proposalPublicId: String,
    val expectedRowVersion: Long,
    val confirmedAmountCents: Long?,
)

internal class ProposalTestActions(
    private val canModify: Boolean = true,
    var listResult: Result<List<MemberRepaymentProposal>> = Result.success(emptyList()),
    var proposalResult: Result<MemberRepaymentProposal> = Result.success(sampleMemberProposal()),
    var confirmResult: Result<Debt> = Result.success(sampleMemberDebt()),
    var forgiveResult: Result<Debt> = Result.success(sampleMemberDebt(status = DebtLinkStatuses.CLEARED, isForgiven = true)),
) : DebtProposalActions {
    val proposeCalls = mutableListOf<ProposalCreateCall>()
    val withdrawCalls = mutableListOf<Pair<String, String>>()
    val confirmCalls = mutableListOf<ProposalConfirmCall>()
    val rejectCalls = mutableListOf<Pair<String, String>>()
    val forgiveCalls = mutableListOf<Pair<String, Long>>()
    var listCalls = 0

    /** When set, listRepaymentProposals() stalls until completed — used to interleave a slow load. */
    var listGate: CompletableDeferred<Unit>? = null
    var proposeGate: CompletableDeferred<Unit>? = null

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun listRepaymentProposals(debtPublicId: String): Result<List<MemberRepaymentProposal>> {
        listCalls++
        // Capture the result at entry so a stalled load returns the snapshot it started with, even
        // if a newer load swaps listResult in the meantime.
        val captured = listResult
        listGate?.await()
        return captured
    }

    override suspend fun proposeRepayment(
        debtPublicId: String,
        proposedAmountCents: Long,
        note: String?,
        supersedesProposalPublicId: String?,
    ): Result<MemberRepaymentProposal> {
        proposeCalls += ProposalCreateCall(debtPublicId, proposedAmountCents, note, supersedesProposalPublicId)
        val captured = proposalResult
        proposeGate?.await()
        return captured
    }

    override suspend fun withdrawRepaymentProposal(
        debtPublicId: String,
        proposalPublicId: String,
    ): Result<MemberRepaymentProposal> {
        withdrawCalls += debtPublicId to proposalPublicId
        return proposalResult
    }

    override suspend fun confirmRepaymentProposal(
        debtPublicId: String,
        proposalPublicId: String,
        expectedRowVersion: Long,
        confirmedAmountCents: Long?,
    ): Result<Debt> {
        confirmCalls += ProposalConfirmCall(debtPublicId, proposalPublicId, expectedRowVersion, confirmedAmountCents)
        return confirmResult
    }

    override suspend fun rejectRepaymentProposal(
        debtPublicId: String,
        proposalPublicId: String,
    ): Result<MemberRepaymentProposal> {
        rejectCalls += debtPublicId to proposalPublicId
        return proposalResult
    }

    override suspend fun forgiveDebt(debtPublicId: String, expectedRowVersion: Long): Result<Debt> {
        forgiveCalls += debtPublicId to expectedRowVersion
        return forgiveResult
    }
}

internal fun sampleMemberProposal(
    publicId: String = "p1",
    proposedAmountCents: Long = 20_000L,
    status: String = MemberProposalStatuses.PENDING,
): MemberRepaymentProposal = MemberRepaymentProposal(
    publicId = publicId,
    debtPublicId = "d1",
    status = status,
    proposedAmountCents = proposedAmountCents,
    confirmedAmountCents = null,
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    paidAt = "2026-06-16T00:00:00Z",
    note = null,
    expiresAt = "2026-07-16T00:00:00Z",
    createdAt = "2026-06-16T00:00:00Z",
    resolvedAt = null,
    supersedesProposalPublicId = null,
    committedRepaymentPublicId = null,
)

internal fun sampleMemberDebt(
    status: String = DebtLinkStatuses.CLEARED,
    isForgiven: Boolean = false,
): Debt = Debt(
    publicId = "d1",
    ledgerId = "owner",
    direction = DebtDirections.OWED_TO_ME,
    counterpartyType = DebtCounterpartyTypes.MEMBER,
    counterpartyAccountId = 42,
    counterpartyLabel = "家人",
    principalAmountCents = 20_000,
    remainingAmountCents = 0,
    paidAmountCents = 20_000,
    status = status,
    sourceType = DebtSourceTypes.BILL_SPLIT,
    sourceId = "inv-1",
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-16T00:00:00Z",
    updatedAt = "2026-06-16T00:00:00Z",
    rowVersion = 6,
    isForgiven = isForgiven,
)
