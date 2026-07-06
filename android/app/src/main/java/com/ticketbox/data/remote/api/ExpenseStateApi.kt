package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseRepaymentDraftCreateRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import com.ticketbox.data.remote.dto.StatusDto
import retrofit2.http.Body
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path

interface ExpenseStateApi {
    @POST("api/expenses/{id}/confirm")
    suspend fun confirmExpense(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    @POST("api/expenses/{id}/reject")
    suspend fun rejectExpense(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    // ADR-0038 undo: restore a recently-rejected expense (5-min window). No
    // request body — the caller just rejected the row and there's near-zero
    // contention inside the window. 404 ``expense_not_found`` once the window
    // closes / row was never rejected / cross-tenant — same collapse semantic
    // as merchant_alias / category_rule undo. Online-only: an offline Queued
    // reject has nothing to restore via the API (its rejection lives in the
    // outbox, not the server); UI should only show the undo affordance after
    // an ExpenseStateOutcome.Synced reject.
    // ADR-0038 PR-A: undo now carries expected_row_version — rejects stale
    // /undo from a banner whose row has been re-rejected since the banner
    // was shown. Without it a cached banner could un-do a NEW intentional
    // reject.
    @POST("api/expenses/{id}/undo")
    suspend fun undoExpense(
        @Path("id") id: Long,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
    ): ExpenseDto

    @POST("api/expenses/{id}/ocr/retry")
    suspend fun retryOcr(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    // ADR-0042 Slice E-2: client supplies ``raw_text`` and the server parses it
    // into the draft fields (DISTINCT from retryOcr, which re-runs the server OCR
    // provider on the stored image). Body-carrying like replaceExpenseItems.
    @POST("api/expenses/{id}/recognize-text")
    suspend fun recognizeText(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    @POST("api/expenses/{id}/suggestions/{decisionPublicId}/accept")
    suspend fun acceptPendingSuggestion(
        @Path("id") id: Long,
        @Path("decisionPublicId") decisionPublicId: String,
    ): StatusDto

    @POST("api/expenses/{id}/suggestions/{decisionPublicId}/reject")
    suspend fun rejectPendingSuggestion(
        @Path("id") id: Long,
        @Path("decisionPublicId") decisionPublicId: String,
    ): StatusDto

    @POST("api/expenses/{id}/mark-not-duplicate")
    suspend fun markNotDuplicate(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    @POST("api/expenses/{id}/repayment-draft")
    suspend fun createRepaymentDraftFromExpense(
        @Path("id") id: String,
        @Body request: ExpenseRepaymentDraftCreateRequestDto,
    ): RepaymentDraftDto
}
