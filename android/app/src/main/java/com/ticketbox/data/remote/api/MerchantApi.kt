package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.MerchantAliasDeleteRequest
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasListDto
import com.ticketbox.data.remote.dto.MerchantAliasRequest
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogCreateRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDeleteRequest
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogListDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeDto
import com.ticketbox.data.remote.dto.MerchantCatalogMergeRequest
import com.ticketbox.data.remote.dto.MerchantCatalogUpdateRequest
import com.ticketbox.data.remote.dto.StatusDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.HTTP
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface MerchantApi {
    @GET("api/merchants/catalog")
    suspend fun merchantCatalog(
        @Query("include_hidden") includeHidden: Boolean = true,
    ): MerchantCatalogListDto

    @POST("api/merchants/catalog")
    suspend fun createMerchantCatalog(@Body request: MerchantCatalogCreateRequest): MerchantCatalogDto

    @PATCH("api/merchants/catalog/{publicId}")
    suspend fun updateMerchantCatalog(
        @Path("publicId") publicId: String,
        @Body request: MerchantCatalogUpdateRequest,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MerchantCatalogDto

    @HTTP(method = "DELETE", path = "api/merchants/catalog/{publicId}", hasBody = true)
    suspend fun deleteMerchantCatalog(
        @Path("publicId") publicId: String,
        @Body request: MerchantCatalogDeleteRequest,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MerchantCatalogDto

    @POST("api/merchants/catalog/{sourcePublicId}/merge")
    suspend fun mergeMerchantCatalog(
        @Path("sourcePublicId") sourcePublicId: String,
        @Body request: MerchantCatalogMergeRequest,
    ): MerchantCatalogMergeDto

    @GET("api/merchants/aliases")
    suspend fun merchantAliases(): MerchantAliasListDto

    @POST("api/merchants/aliases")
    suspend fun createMerchantAlias(@Body request: MerchantAliasRequest): MerchantAliasDto

    @PATCH("api/merchants/aliases/{publicId}")
    suspend fun updateMerchantAlias(
        @Path("publicId") publicId: String,
        @Body request: MerchantAliasUpdateRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): MerchantAliasDto

    @HTTP(method = "DELETE", path = "api/merchants/aliases/{publicId}", hasBody = true)
    suspend fun deleteMerchantAlias(
        @Path("publicId") publicId: String,
        @Body request: MerchantAliasDeleteRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): StatusDto

    // ADR-0038 undo: restore a soft-deleted alias (no body / token — it
    // restores the row the caller just deleted). Returns the restored alias.
    @POST("api/merchants/aliases/{publicId}/undo")
    suspend fun undoMerchantAlias(@Path("publicId") publicId: String): MerchantAliasDto
}
