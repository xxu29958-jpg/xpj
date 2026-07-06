package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalConfirmRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalCreateRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalListResponseDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalRejectRequestDto
import com.ticketbox.data.remote.dto.MemberRepaymentProposalWithdrawRequestDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path

interface DebtProposalApi {
    // ADR-0049 §3.2 (slice 8d) member repayment proposals. The two parties of a member Debt can
    // live in different ledgers (a bill_split Debt is owned by the receiver, sender = cross-ledger
    // creditor), so these routes are participant-scoped (§5.2), not ledger-scoped. The debtor
    // proposes "I paid" / withdraws; the creditor confirms (full or partial) / rejects. Confirm is
    // fold-changing → it carries expected_row_version in the body + replies with the fold-after
    // DebtResponse (DebtDto); the other writes reply with the proposal's own response. Every write
    // carries an ADR-0042 intent-time idempotency key (nullable for Retrofit ergonomics — the
    // repository always supplies a UUID). The list GET is read-only (no key).
    @GET("api/debts/{publicId}/repayment-proposals")
    suspend fun repaymentProposals(
        @Path("publicId") publicId: String,
    ): MemberRepaymentProposalListResponseDto

    @POST("api/debts/{publicId}/repayment-proposals")
    suspend fun createRepaymentProposal(
        @Path("publicId") publicId: String,
        @Body request: MemberRepaymentProposalCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MemberRepaymentProposalDto

    @POST("api/debts/{publicId}/repayment-proposals/{proposalPublicId}/withdraw")
    suspend fun withdrawRepaymentProposal(
        @Path("publicId") publicId: String,
        @Path("proposalPublicId") proposalPublicId: String,
        @Body request: MemberRepaymentProposalWithdrawRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MemberRepaymentProposalDto

    @POST("api/debts/{publicId}/repayment-proposals/{proposalPublicId}/confirm")
    suspend fun confirmRepaymentProposal(
        @Path("publicId") publicId: String,
        @Path("proposalPublicId") proposalPublicId: String,
        @Body request: MemberRepaymentProposalConfirmRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto

    @POST("api/debts/{publicId}/repayment-proposals/{proposalPublicId}/reject")
    suspend fun rejectRepaymentProposal(
        @Path("publicId") publicId: String,
        @Path("proposalPublicId") proposalPublicId: String,
        @Body request: MemberRepaymentProposalRejectRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MemberRepaymentProposalDto
}
