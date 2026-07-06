package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PATCH
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.PUT

interface ExpenseDetailApi {
    @GET("api/expenses/{id}")
    suspend fun expense(@Path("id") id: Long): ExpenseDto

    @PATCH("api/expenses/{id}")
    suspend fun updateExpense(
        // issue #65 slice 3: server-id-or-``local:{client_ref}`` string ref.
        @Path("id") id: String,
        @Body request: ExpenseUpdateRequest,
        // ADR-0042: intent-time idempotency key. A committed-but-unseen replay
        // (direct PATCH commits server-side but the response is lost, then the
        // outbox replays) carries the SAME key so the server HITs and returns
        // the canonical row instead of false-409ing on the now-stale
        // expected_row_version. Nullable for Retrofit ergonomics (a null value
        // is omitted from the request); the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseDto

    @GET("api/expenses/{id}/items")
    suspend fun expenseItems(@Path("id") id: Long): ExpenseItemsResponseDto

    @PUT("api/expenses/{id}/items")
    suspend fun replaceExpenseItems(
        @Path("id") id: String,
        @Body request: ExpenseItemReplaceRequestDto,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseItemsResponseDto

    @POST("api/expenses/{id}/items/acknowledge-mismatch")
    suspend fun acknowledgeExpenseItemsMismatch(
        @Path("id") id: String,
        @Body request: com.ticketbox.data.remote.dto.ExpenseStateTokenRequest,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseItemsResponseDto

    @GET("api/expenses/{id}/splits")
    suspend fun expenseSplits(@Path("id") id: Long): ExpenseSplitsResponseDto

    @PUT("api/expenses/{id}/splits")
    suspend fun replaceExpenseSplits(
        @Path("id") id: String,
        @Body request: ExpenseSplitReplaceRequestDto,
        // ADR-0042: intent-time idempotency key (see updateExpense). Nullable
        // for Retrofit ergonomics; the repository always supplies a UUID.
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseSplitsResponseDto
}
