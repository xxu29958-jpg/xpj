package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.LedgerCreateRequestDto
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberRoleUpdateRequestDto
import com.ticketbox.data.remote.dto.LedgerSwitchResponseDto
import com.ticketbox.data.remote.dto.LedgerAuditListResponseDto
import com.ticketbox.data.remote.dto.LedgerMemberDto
import com.ticketbox.data.remote.dto.OwnerTransferResponseDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface LedgerApi {
    @GET("api/ledgers")
    suspend fun listLedgers(): LedgerListResponseDto

    @POST("api/ledgers")
    suspend fun createLedger(@Body request: LedgerCreateRequestDto): com.ticketbox.data.remote.dto.LedgerDto

    @POST("api/ledgers/{ledgerId}/switch")
    suspend fun switchLedger(@Path("ledgerId") ledgerId: String): LedgerSwitchResponseDto

    @GET("api/ledgers/{ledgerId}/members")
    suspend fun ledgerMembers(@Path("ledgerId") ledgerId: String): LedgerMemberListResponseDto

    @GET("api/ledgers/{ledgerId}/audit")
    suspend fun ledgerAudit(
        @Path("ledgerId") ledgerId: String,
        @Query("limit") limit: Int = 100,
    ): LedgerAuditListResponseDto

    @POST("api/ledgers/{ledgerId}/members/{memberId}/role")
    suspend fun updateLedgerMemberRole(
        @Path("ledgerId") ledgerId: String,
        @Path("memberId") memberId: Long,
        @Body request: LedgerMemberRoleUpdateRequestDto,
    ): LedgerMemberDto

    @POST("api/ledgers/{ledgerId}/members/{memberId}/disable")
    suspend fun disableLedgerMember(
        @Path("ledgerId") ledgerId: String,
        @Path("memberId") memberId: Long,
    ): LedgerMemberDto

    @POST("api/ledgers/{ledgerId}/members/{memberId}/transfer-owner")
    suspend fun transferLedgerOwner(
        @Path("ledgerId") ledgerId: String,
        @Path("memberId") memberId: Long,
    ): OwnerTransferResponseDto
}
