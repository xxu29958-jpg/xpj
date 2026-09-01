package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.ConfirmedExpenseBatchUpdateRequestDto
import com.ticketbox.data.remote.dto.ConfirmedExpenseBatchUpdateResponseDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionResponseDto
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetVoidRequestDto
import com.ticketbox.data.remote.dto.ExpenseRevisionPageDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

interface ExpenseCorrectionApi {
    @GET("api/expenses/{id}/fact-bundle")
    suspend fun expenseFactBundle(
        @Path("id") id: String,
    ): ExpenseFactBundleDto

    @POST("api/expenses/{id}/offsets")
    suspend fun createExpenseOffset(
        @Path("id") id: String,
        @Body request: ExpenseOffsetCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String,
    ): ExpenseFactBundleDto

    @POST("api/expenses/{id}/offsets/{offsetPublicId}/voids")
    suspend fun voidExpenseOffset(
        @Path("id") id: String,
        @Path("offsetPublicId") offsetPublicId: String,
        @Body request: ExpenseOffsetVoidRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String,
    ): ExpenseFactBundleDto

    @POST("api/expenses/{id}/corrections")
    suspend fun correctExpense(
        @Path("id") id: String,
        @Body request: ExpenseCorrectionRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): ExpenseCorrectionResponseDto

    @GET("api/expenses/{id}/revisions")
    suspend fun expenseRevisions(
        @Path("id") id: Long,
        @Query("page") page: Int = 1,
        @Query("page_size") pageSize: Int = 50,
        @Query("snapshot_revision") snapshotRevision: Long? = null,
    ): ExpenseRevisionPageDto

    @POST("api/expenses/confirmed/batch-update")
    suspend fun updateConfirmedBatch(
        @Header("Idempotency-Key") idempotencyKey: String,
        @Body request: ConfirmedExpenseBatchUpdateRequestDto,
    ): ConfirmedExpenseBatchUpdateResponseDto
}
