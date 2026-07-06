package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.RepaymentDraftDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface RepaymentDraftApi {
    // ADR-0049 §杠杆③ (slice 3a): NLS repayment-capture inbox. The list is ledger-scoped via the
    // session token (default status=pending). Create posts one NLS-captured repayment as a PENDING
    // draft (never auto-records — §8); it is content+identity deduped server-side, so it carries no
    // OCC token (its safe-replay rests on the dedup key) — the repository does not mint an
    // Idempotency-Key for it. Confirm records ONE Repayment against the chosen open external/manual
    // Debt → fold-changing, so it carries expected_row_version in the body + an ADR-0042 intent-time
    // idempotency key in the header (nullable for Retrofit ergonomics — the repository supplies a
    // UUID). Dismiss latches the draft dismissed (no token). All three resolution routes return the
    // re-serialized RepaymentDraftResponse.
    @GET("api/repayment-drafts")
    suspend fun repaymentDrafts(
        @Query("status") status: String? = null,
    ): com.ticketbox.data.remote.dto.RepaymentDraftListResponseDto

    @POST("api/repayment-drafts")
    suspend fun createRepaymentDraft(
        @Body request: com.ticketbox.data.remote.dto.RepaymentDraftCreateRequestDto,
    ): com.ticketbox.data.remote.dto.RepaymentDraftDto

    @POST("api/repayment-drafts/{publicId}/confirm")
    suspend fun confirmRepaymentDraft(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): com.ticketbox.data.remote.dto.RepaymentDraftDto

    @POST("api/repayment-drafts/{publicId}/dismiss")
    suspend fun dismissRepaymentDraft(
        @Path("publicId") publicId: String,
        @Body request: com.ticketbox.data.remote.dto.RepaymentDraftDismissRequestDto,
    ): com.ticketbox.data.remote.dto.RepaymentDraftDto
}
