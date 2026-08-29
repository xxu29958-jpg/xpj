package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.RecurringCandidateConfirmRequestDto
import com.ticketbox.data.remote.dto.RecurringCandidatesResponseDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import com.ticketbox.data.remote.dto.DataQualitySummaryDto
import retrofit2.http.Header
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface RecurringApi {
    @GET("api/insights/recurring-candidates")
    suspend fun recurringCandidates(
        @Query("timezone") timezone: String? = null,
    ): RecurringCandidatesResponseDto

    @GET("api/recurring/items")
    suspend fun recurringItems(
        @Query("status") status: String? = null,
        @Query("include_archived") includeArchived: Boolean = false,
        @Query("month") month: String? = null,
        @Query("timezone") timezone: String? = null,
    ): RecurringItemListResponseDto

    @POST("api/recurring/items")
    suspend fun createRecurringItem(
        @Body request: RecurringItemCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String,
    ): RecurringItemDto

    @POST("api/recurring/from-candidate")
    suspend fun confirmRecurringCandidate(
        @Body request: RecurringCandidateConfirmRequestDto,
        @Query("timezone") timezone: String? = null,
    ): RecurringItemDto

    @PATCH("api/recurring/items/{publicId}")
    suspend fun updateRecurringItem(
        @Path("publicId") publicId: String,
        @Body request: RecurringItemUpdateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String,
    ): RecurringItemDto

    @POST("api/recurring/items/{publicId}/pause")
    suspend fun pauseRecurringItem(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest,
    ): RecurringItemDto

    @POST("api/recurring/items/{publicId}/resume")
    suspend fun resumeRecurringItem(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest,
    ): RecurringItemDto

    @POST("api/recurring/items/{publicId}/archive")
    suspend fun archiveRecurringItem(@Path("publicId") publicId: String): RecurringItemDto

    @POST("api/recurring/items/{publicId}/restore")
    suspend fun restoreRecurringItem(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.RecurringItemTokenRequest,
    ): RecurringItemDto

    @GET("api/insights/data-quality")
    suspend fun dataQualitySummary(): DataQualitySummaryDto
}
