package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.CategoryRuleDeleteRequest
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.CategoryRuleUpdateRequest
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.data.remote.dto.StatusDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.HTTP
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface CategoryRuleApi {
    @GET("api/rules/categories")
    suspend fun categoryRules(): List<CategoryRuleDto>

    @POST("api/rules/categories")
    suspend fun createCategoryRule(@Body request: CategoryRuleRequest): CategoryRuleDto

    @PATCH("api/rules/categories/{id}")
    suspend fun updateCategoryRule(
        @Path("id") id: Long,
        @Body request: CategoryRuleUpdateRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): CategoryRuleDto

    @HTTP(method = "DELETE", path = "api/rules/categories/{id}", hasBody = true)
    suspend fun deleteCategoryRule(
        @Path("id") id: Long,
        @Body request: CategoryRuleDeleteRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): StatusDto

    // ADR-0038 undo: restore a soft-deleted category rule (no body / token — it
    // restores the row the caller just deleted). Returns the restored rule.
    @POST("api/rules/categories/{id}/undo")
    suspend fun undoCategoryRule(@Path("id") id: Long): CategoryRuleDto

    @GET("api/rules/applications")
    suspend fun ruleApplications(
        @Query("limit") limit: Int = 20,
    ): RuleApplicationListDto

    @POST("api/rules/applications/{publicId}/rollback")
    suspend fun rollbackRuleApplication(
        @Path("publicId") publicId: String,
    ): RuleApplicationRollbackDto

    @POST("api/rules/apply-confirmed")
    suspend fun applyConfirmedRules(
        @Body request: RuleApplyConfirmedRequestDto = RuleApplyConfirmedRequestDto(),
        @Query("limit") limit: Int = 20,
        @Query("max_scan") maxScan: Int = 500,
    ): RuleApplyConfirmedResponseDto
}
