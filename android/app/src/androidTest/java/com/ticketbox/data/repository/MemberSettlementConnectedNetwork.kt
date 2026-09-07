package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtForgiveCreateRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalConfirmRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalListResponseDto
import com.ticketbox.data.remote.dto.RepaymentFactDto
import com.ticketbox.data.remote.dto.RepaymentFactListDto
import java.io.IOException
import java.lang.reflect.Proxy

/** Synthetic peer-side server IO; production graph, Room, UI and currency consumers remain real. */
internal class MemberSettlementConnectedNetwork {
    var current = DebtDto(
        publicId = "member-original", ledgerId = null, direction = "i_owe", counterpartyType = "member",
        counterpartyAccountId = 42, counterpartyLabel = "小林", principalAmountCents = 1200,
        remainingAmountCents = 1200, paidAmountCents = 0, status = "open", sourceType = "bill_split",
        sourceId = "split-original", homeCurrencyCode = "JPY", viewerIsDebtor = false,
        createdAt = "2026-09-08T00:00:00Z", updatedAt = "2026-09-08T00:00:00Z", rowVersion = 1,
    )
    var proposal = MemberRepaymentProposalDto(
        publicId = "proposal-original", debtPublicId = current.publicId, status = "pending", proposedAmountCents = 750,
        homeCurrencyCode = "JPY", paidAt = current.createdAt, expiresAt = "2026-10-08T00:00:00Z", createdAt = current.createdAt,
    )
    val confirms = mutableListOf<Pair<MemberRepaymentProposalConfirmRequestDto, String>>()
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
            return MemberRepaymentProposalListResponseDto(listOf(proposal))
        }

        override suspend fun confirmRepaymentProposal(publicId: String, proposalPublicId: String,
            request: MemberRepaymentProposalConfirmRequestDto, idempotencyKey: String?): DebtDto {
            check(publicId == current.publicId && proposalPublicId == proposal.publicId)
            val key = requireNotNull(idempotencyKey)
            confirms += request to key
            val result = accepted.getOrPut(key) {
                check(request.expectedRowVersion == current.rowVersion)
                val amount = request.confirmedAmountCents ?: proposal.proposedAmountCents
                payment = RepaymentFactDto("payment-original", amount, current.createdAt, current.createdAt, "active")
                proposal = proposal.copy(status = if (amount < proposal.proposedAmountCents) "partially_confirmed" else "confirmed", confirmedAmountCents = amount,
                    committedRepaymentPublicId = "payment-original", resolvedAt = current.createdAt)
                current.copy(remainingAmountCents = current.remainingAmountCents - amount,
                    paidAmountCents = amount, rowVersion = current.rowVersion + 1).also { current = it }
            }
            failReads = true
            if (loseFirstResponse) { loseFirstResponse = false; throw IOException("Synthetic lost acknowledgement") }
            return result
        }

        override suspend fun debtRepayments(publicId: String, page: Int): RepaymentFactListDto {
            check(publicId == current.publicId)
            val items = listOfNotNull(payment)
            return RepaymentFactListDto(publicId, "JPY", items, page, 20, items.size)
        }

        override suspend fun forgiveDebt(publicId: String, request: DebtForgiveCreateRequestDto,
            idempotencyKey: String?): DebtDto {
            check(publicId == current.publicId && request.expectedRowVersion == current.rowVersion)
            return accepted.getOrPut(requireNotNull(idempotencyKey)) {
                current.copy(remainingAmountCents = 0, status = "cleared", isForgiven = true,
                    rowVersion = current.rowVersion + 1).also { current = it }
            }
        }
    }
}

private fun unexpectedMemberApi(): ApiService = Proxy.newProxyInstance(
    ApiService::class.java.classLoader, arrayOf(ApiService::class.java),
) { _, method, _ -> error("Unexpected member IO: ${method.name}") } as ApiService
