package com.ticketbox.data.remote.api

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface BillSplitApi {
    // ADR-0029 bill split workflow
    @POST("api/expenses/{id}/split-invite")
    suspend fun createBillSplitInvitation(
        @Path("id") id: Long,
        @Body request: com.ticketbox.data.remote.dto.BillSplitInviteRequestDto,
    ): com.ticketbox.data.remote.dto.BillSplitSentDto

    @GET("api/bill-splits/inbox")
    suspend fun listBillSplitInbox(
        @Query("status") status: String? = null,
    ): com.ticketbox.data.remote.dto.BillSplitInboxListResponseDto

    @GET("api/bill-splits/sent")
    suspend fun listBillSplitSent(): com.ticketbox.data.remote.dto.BillSplitSentListResponseDto

    @POST("api/bill-splits/{publicId}/accept")
    suspend fun acceptBillSplitInvitation(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.BillSplitAcceptRequestDto,
    ): com.ticketbox.data.remote.dto.BillSplitInboxDto

    @POST("api/bill-splits/{publicId}/reject")
    suspend fun rejectBillSplitInvitation(
        @Path("publicId") publicId: String,
    ): com.ticketbox.data.remote.dto.BillSplitInboxDto

    @POST("api/bill-splits/{publicId}/cancel")
    suspend fun cancelBillSplitInvitation(
        @Path("publicId") publicId: String,
    ): com.ticketbox.data.remote.dto.BillSplitSentDto
}
