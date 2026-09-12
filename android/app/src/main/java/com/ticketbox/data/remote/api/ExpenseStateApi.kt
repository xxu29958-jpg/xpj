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

    // The original rejection token and intent key survive an unknown response.
    // A later rejection must never become this Undo's new OCC basis.
    @POST("api/expenses/{id}/undo")
    suspend fun undoExpense(
        @Path("id") id: Long,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        @Header("Idempotency-Key") idempotencyKey: String,
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
