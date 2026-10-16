package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtForgiveCreateRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalConfirmRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentCalendarDto
import com.ticketbox.data.remote.dto.ExpenseAccountingTimeDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalListResponseDto
import com.ticketbox.data.remote.dto.RepaymentFactDto
import java.io.IOException
import java.lang.reflect.Proxy

/** Declared member-command replies; Room, UI and client currency consumers remain real. */
internal class MemberSettlementConnectedNetwork {
    var current = DebtDto(
        publicId = "member-original", ledgerId = null, direction = "i_owe", counterpartyType = "member",
        counterpartyAccountId = 42, counterpartyLabel = "小林", principalAmountCents = 1200,
        remainingAmountCents = 1200, paidAmountCents = 0, status = "open", sourceType = "bill_split",
        sourceId = "split-original", homeCurrencyCode = "JPY", viewerIsDebtor = false,
        createdAt = "2026-09-08T00:00:00Z", updatedAt = "2026-09-08T00:00:00Z", rowVersion = 1,
        repaymentCalendar = RepaymentCalendarDto(3, "Asia/Shanghai"),
    )
    var proposal = MemberRepaymentProposalDto(
        publicId = "proposal-original", debtPublicId = current.publicId, status = "pending", proposedAmountCents = 750,
        homeCurrencyCode = "JPY", paidAt = current.createdAt, expiresAt = "2026-10-08T00:00:00Z", createdAt = current.createdAt,
    )
    val confirms = mutableListOf<Pair<MemberRepaymentProposalConfirmRequestDto, String>>()
    val proposes = mutableListOf<Pair<MemberRepaymentProposalCreateRequestDto, String>>()
    val acceptedProposals = mutableMapOf<String, MemberRepaymentProposalDto>()
    var hasProposal = true
    val accepted = mutableMapOf<String, DebtDto>()
    var failReads = false
    var failProposalReads = false
    var loseFirstResponse = true
    private var payment: RepaymentFactDto? = null
    val service = object : ApiService by unexpectedMemberApi() {
        override suspend fun debt(publicId: String): DebtDto {
            check(publicId == current.publicId)
            if (failReads) throw IOException("Synthetic unavailable debt read")
            return current
        }

        override suspend fun repaymentProposals(publicId: String): MemberRepaymentProposalListResponseDto {
            check(publicId == current.publicId)
            if (failReads || failProposalReads) throw IOException("Synthetic unavailable proposal read")
            return MemberRepaymentProposalListResponseDto(if (hasProposal) listOf(proposal) else emptyList())
        }

        override suspend fun createRepaymentProposal(publicId: String, request: MemberRepaymentProposalCreateRequestDto,
            idempotencyKey: String?): MemberRepaymentProposalDto {
            check(publicId == current.publicId)
            val key = requireNotNull(idempotencyKey)
            proposes += request to key
            val result = acceptedProposals.getOrPut(key) {
                val time = requireNotNull(request.timeInput)
                check(time.precision == "date_only" && time.instantUtc == null)
                proposal.copy(proposedAmountCents = request.proposedAmountCents, note = request.note, paidAt = null,
                    accountingTime = ExpenseAccountingTimeDto(time.precision, userLocalDate = time.userLocalDate,
                        accountingDate = time.accountingDate, sourceTimezone = time.sourceTimezone, calendarRevision = time.calendarRevision))
                    .also { proposal = it; hasProposal = true }
            }
            if (loseFirstResponse) { loseFirstResponse = false; failReads = true; throw IOException("Synthetic lost acknowledgement") }
            return result
        }

        override suspend fun confirmRepaymentProposal(publicId: String, proposalPublicId: String,
            request: MemberRepaymentProposalConfirmRequestDto, idempotencyKey: String?): DebtDto {
            check(publicId == current.publicId && proposalPublicId == proposal.publicId)
            val key = requireNotNull(idempotencyKey)
            confirms += request to key
            val result = accepted.getOrPut(key) {
                check(request.expectedRowVersion == 1L && request.confirmedAmountCents == 450L)
                payment = RepaymentFactDto("payment-original", 450, current.createdAt, current.createdAt, "active")
                proposal = proposal.copy(status = "partially_confirmed", confirmedAmountCents = 450,
                    committedRepaymentPublicId = "payment-original", resolvedAt = current.createdAt)
                current.copy(remainingAmountCents = 750, paidAmountCents = 450, rowVersion = 2).also { current = it }
            }
            failReads = true
            if (loseFirstResponse) { loseFirstResponse = false; throw IOException("Synthetic lost acknowledgement") }
            return result
        }

        override suspend fun debtActivity(publicId: String, page: Int, focusRepayment: String?): com.ticketbox.data.remote.dto.DebtActivityListDto {
            check(publicId == current.publicId)
            val events = listOfNotNull(payment).map { payment -> com.ticketbox.data.remote.dto.DebtActivityDto(
                kind = "repayment", publicId = payment.publicId, recordedAt = payment.createdAt,
                actorIsYou = true, repayment = payment,
            ) }
            val proposalEvents = if (hasProposal) listOfNotNull(
                com.ticketbox.data.remote.dto.DebtActivityDto("proposal_created", proposal.publicId, proposal.createdAt,
                    actorIsYou = false, proposal = proposal),
                proposal.resolvedAt?.let { com.ticketbox.data.remote.dto.DebtActivityDto("proposal_resolved", proposal.publicId, it,
                    actorIsYou = true, proposal = proposal) },
            ) else emptyList()
            return com.ticketbox.data.remote.dto.DebtActivityListDto(publicId, "JPY",
                events + proposalEvents, page, 20, events.size + proposalEvents.size)
        }

        override suspend fun forgiveDebt(publicId: String, request: DebtForgiveCreateRequestDto,
            idempotencyKey: String?): DebtDto {
            check(publicId == current.publicId && request.expectedRowVersion == 2L)
            return accepted.getOrPut(requireNotNull(idempotencyKey)) {
                current.copy(remainingAmountCents = 0, paidAmountCents = 450, status = "cleared", isForgiven = true,
                    rowVersion = 3).also { current = it }
            }
        }
    }
}

private fun unexpectedMemberApi(): ApiService = Proxy.newProxyInstance(
    ApiService::class.java.classLoader, arrayOf(ApiService::class.java),
) { _, method, _ -> error("Unexpected member IO: ${method.name}") } as ApiService
