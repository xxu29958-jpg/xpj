package com.ticketbox.data.remote.api

import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.HTTP
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface IncomePlanApi {
    // v1.1 income plans (PR-7 routes) + budget advisor (PR-7 + PR-8)
    @GET("api/income-plans")
    suspend fun listIncomePlans(
        @Query("status") status: String = "active",
    ): com.ticketbox.data.remote.dto.IncomePlanListResponseDto

    @POST("api/income-plans")
    suspend fun createIncomePlan(
        @Body request: com.ticketbox.data.remote.dto.IncomePlanCreateRequestDto,
    ): com.ticketbox.data.remote.dto.IncomePlanDto

    @PATCH("api/income-plans/{publicId}")
    suspend fun updateIncomePlan(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.IncomePlanDto

    @HTTP(method = "DELETE", path = "api/income-plans/{publicId}", hasBody = true)
    suspend fun archiveIncomePlan(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto,
    ): com.ticketbox.data.remote.dto.IncomePlanDto

    @POST("api/income-plans/{publicId}/restore")
    suspend fun restoreIncomePlan(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.IncomePlanTokenRequestDto,
    ): com.ticketbox.data.remote.dto.IncomePlanDto
}
