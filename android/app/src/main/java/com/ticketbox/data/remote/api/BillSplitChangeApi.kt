package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.BillSplitAgreementDto
import com.ticketbox.data.remote.dto.BillSplitChangeAcceptRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeCreateRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeEmptyRequestDto
import com.ticketbox.data.remote.dto.BillSplitChangeProposalDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface BillSplitChangeApi {
    @GET("api/debts/{publicId}/split-agreement")
    suspend fun splitAgreement(
        @Path("publicId") publicId: String,
        @Query("new_share_amount_cents") newShareAmountCents: Long? = null,
    ): BillSplitAgreementDto

    @POST("api/debts/{publicId}/split-change-proposals")
    suspend fun createSplitChangeProposal(
        @Path("publicId") publicId: String,
        @Body request: BillSplitChangeCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): BillSplitChangeProposalDto

    @POST("api/debts/{publicId}/split-change-proposals/{proposalPublicId}/accept")
    suspend fun acceptSplitChangeProposal(
        @Path("publicId") publicId: String,
        @Path("proposalPublicId") proposalPublicId: String,
        @Body request: BillSplitChangeAcceptRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): BillSplitAgreementDto

    @POST("api/debts/{publicId}/split-change-proposals/{proposalPublicId}/reject")
    suspend fun rejectSplitChangeProposal(
        @Path("publicId") publicId: String,
        @Path("proposalPublicId") proposalPublicId: String,
        @Body request: BillSplitChangeEmptyRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): BillSplitChangeProposalDto

    @POST("api/debts/{publicId}/split-change-proposals/{proposalPublicId}/withdraw")
    suspend fun withdrawSplitChangeProposal(
        @Path("publicId") publicId: String,
        @Path("proposalPublicId") proposalPublicId: String,
        @Body request: BillSplitChangeEmptyRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): BillSplitChangeProposalDto
}
