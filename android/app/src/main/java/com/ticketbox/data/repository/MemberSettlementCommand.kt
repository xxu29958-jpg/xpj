package com.ticketbox.data.repository

import com.squareup.moshi.JsonClass
import com.ticketbox.data.remote.dto.ExpenseTimeInputDto
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.MemberRepaymentProposal

/** The displayed obligation and its original authenticated context. */
data class DebtTask(val binding: LogicalSessionBinding, val debtPublicId: String)

/** Existing server commands; their value equality identifies an unchanged explicit retry. */
sealed interface MemberSettlementCommand {
    @JsonClass(generateAdapter = true)
    data class Propose(val amountCents: Long, val note: String?, val supersedesProposalPublicId: String? = null,
        val timeInput: ExpenseTimeInputDto? = null) : MemberSettlementCommand
    @JsonClass(generateAdapter = true)
    data class Confirm(val proposalPublicId: String, val expectedRowVersion: Long, val amountCents: Long?) : MemberSettlementCommand
    @JsonClass(generateAdapter = true)
    data class Withdraw(val proposalPublicId: String) : MemberSettlementCommand
    @JsonClass(generateAdapter = true)
    data class Reject(val proposalPublicId: String) : MemberSettlementCommand
    @JsonClass(generateAdapter = true)
    data class Forgive(val expectedRowVersion: Long) : MemberSettlementCommand
}

/** A proposal acknowledgement is distinct from a committed change to the debt fold. */
sealed interface MemberSettlementResult {
    data class Proposal(val value: MemberRepaymentProposal) : MemberSettlementResult
    data class DebtChanged(val value: Debt) : MemberSettlementResult
}
