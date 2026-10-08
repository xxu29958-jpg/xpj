package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.SavedViewDefinitionRequestDto
import com.ticketbox.data.remote.dto.SavedViewDeleteRequestDto
import com.ticketbox.data.remote.dto.SavedViewDeletionReceiptDto
import com.ticketbox.data.remote.dto.SavedViewDto
import com.ticketbox.data.remote.dto.SavedViewListDto
import com.ticketbox.data.remote.dto.SavedViewResultsDto
import com.ticketbox.data.remote.dto.SavedViewUpdateRequestDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.HTTP
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface SavedViewApi {
    @GET("api/saved-views")
    suspend fun savedViews(): SavedViewListDto

    @GET("api/saved-views/{publicId}")
    suspend fun savedView(@Path("publicId") publicId: String): SavedViewDto

    @GET("api/saved-views/{publicId}/results")
    suspend fun savedViewResults(@Path("publicId") publicId: String, @Query("page") page: Int): SavedViewResultsDto

    @POST("api/saved-views")
    suspend fun createSavedView(
        @Body request: SavedViewDefinitionRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String,
    ): SavedViewDto

    @PATCH("api/saved-views/{publicId}")
    suspend fun updateSavedView(
        @Path("publicId") publicId: String,
        @Body request: SavedViewUpdateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String,
    ): SavedViewDto

    @HTTP(method = "DELETE", path = "api/saved-views/{publicId}", hasBody = true)
    suspend fun deleteSavedView(
        @Path("publicId") publicId: String,
        @Body request: SavedViewDeleteRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String,
    ): SavedViewDeletionReceiptDto
}
