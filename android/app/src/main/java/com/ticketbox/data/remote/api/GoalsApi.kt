package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.DebtGoalIntegrityReviewRequestDto
import com.ticketbox.data.remote.dto.DebtGoalLinksReplaceRequestDto
import com.ticketbox.data.remote.dto.DebtGoalTargetDateRequestDto
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalListResponseDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface GoalsApi {
    @GET("api/goals")
    suspend fun goals(
        @Query("month") month: String? = null,
        @Query("include_archived") includeArchived: Boolean = false,
        // ADR-0049 §6 (slice 7): "debt_repayment" lists the (month-less) debt goals;
        // null/omitted keeps the historical spending_limit month-scoped behaviour.
        @Query("goal_type") goalType: String? = null,
        @Query("timezone") timezone: String? = null,
    ): GoalListResponseDto

    @POST("api/goals")
    suspend fun createGoal(
        @Body request: GoalCreateRequestDto,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    @GET("api/goals/{publicId}")
    suspend fun goal(
        @Path("publicId") publicId: String,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    @PATCH("api/goals/{publicId}")
    suspend fun updateGoal(
        @Path("publicId") publicId: String,
        @Body request: GoalUpdateRequestDto,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    @POST("api/goals/{publicId}/archive")
    suspend fun archiveGoal(
        @Path("publicId") publicId: String,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    // ADR-0049 §6 (slice 7): replace a debt_repayment goal's linked Debt set →
    // a new goal version. OCC token in the body + ADR-0042 intent-time idempotency
    // key in the header (mirrors updateGoal). Returns the fold-after GoalDto.
    @POST("api/goals/{publicId}/debt-links")
    suspend fun replaceGoalDebtLinks(
        @Path("publicId") publicId: String,
        @Body request: DebtGoalLinksReplaceRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    // ADR-0049 §6/F13 (slice 7): acknowledge ("keep for audit") an achieved debt
    // goal version whose linked set carries a debt-voided Debt — clears needs_review
    // for the current version. OCC token in the body + idempotency key in the header.
    @POST("api/goals/{publicId}/integrity-review/acknowledge")
    suspend fun acknowledgeGoalIntegrityReview(
        @Path("publicId") publicId: String,
        @Body request: DebtGoalIntegrityReviewRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
        @Query("timezone") timezone: String? = null,
    ): GoalDto

    // ADR-0049 §7.0 / 8e-6c (slice 8e-6c): set or clear a debt_repayment goal's payoff deadline.
    // OCC token in the body (bumps row_version only, never goal_version) + idempotency key in the
    // header (mirrors the link-replace / integrity-review setters). Returns the fold-after GoalDto.
    @POST("api/goals/{publicId}/target-date")
    suspend fun setGoalTargetDate(
        @Path("publicId") publicId: String,
        @Body request: DebtGoalTargetDateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
        @Query("timezone") timezone: String? = null,
    ): GoalDto
}
