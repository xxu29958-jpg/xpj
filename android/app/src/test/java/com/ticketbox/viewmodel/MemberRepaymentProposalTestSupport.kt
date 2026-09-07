package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtProposalActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.data.repository.MemberSettlementCommand
import com.ticketbox.data.repository.MemberSettlementResult
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import com.ticketbox.domain.model.MemberProposalStatuses
import com.ticketbox.domain.model.MemberRepaymentProposal
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.withContext
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow

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
    canModify: Boolean = true,
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
    val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(memberDebtTask("d1").binding, canModify))
    val commandKeys = mutableListOf<String>()
    var listCalls = 0

    /** When set, listRepaymentProposals() stalls until completed — used to interleave a slow load. */
    var listGate: CompletableDeferred<Unit>? = null
    var proposeGate: CompletableDeferred<Unit>? = null
    var nonCooperative = false

    override fun currentAccess(): LedgerAccessContext? = access.value
    override fun observeAccess(): Flow<LedgerAccessContext?> = access

    override suspend fun listRepaymentProposals(task: DebtTask): Result<List<MemberRepaymentProposal>> {
        listCalls++
        // Capture the result at entry so a stalled load returns the snapshot it started with, even
        // if a newer load swaps listResult in the meantime.
        val captured = listResult
        listGate?.await()
        return captured
    }

    override suspend fun submit(
        task: DebtTask,
        command: MemberSettlementCommand,
        idempotencyKey: String,
    ): Result<MemberSettlementResult> {
        commandKeys += idempotencyKey
        return when (command) {
            is MemberSettlementCommand.Propose -> {
                proposeCalls += ProposalCreateCall(task.debtPublicId, command.amountCents, command.note, command.supersedesProposalPublicId)
                val captured = proposalResult
                if (nonCooperative) withContext(NonCancellable) { proposeGate?.await() } else proposeGate?.await()
                captured.map { MemberSettlementResult.Proposal(it) }
            }
            is MemberSettlementCommand.Confirm -> {
                confirmCalls += ProposalConfirmCall(task.debtPublicId, command.proposalPublicId, command.expectedRowVersion, command.amountCents)
                confirmResult.map { MemberSettlementResult.DebtChanged(it) }
            }
            is MemberSettlementCommand.Withdraw -> {
                withdrawCalls += task.debtPublicId to command.proposalPublicId
                proposalResult.map { MemberSettlementResult.Proposal(it) }
            }
            is MemberSettlementCommand.Reject -> {
                rejectCalls += task.debtPublicId to command.proposalPublicId
                proposalResult.map { MemberSettlementResult.Proposal(it) }
            }
            is MemberSettlementCommand.Forgive -> {
                forgiveCalls += task.debtPublicId to command.expectedRowVersion
                forgiveResult.map { MemberSettlementResult.DebtChanged(it) }
            }
        }
    }
}

internal fun memberDebtTask(publicId: String) = DebtTask(
    LogicalSessionBinding("https://member-test.example", "owner", "test-owner", "session", "revision"), publicId)

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
