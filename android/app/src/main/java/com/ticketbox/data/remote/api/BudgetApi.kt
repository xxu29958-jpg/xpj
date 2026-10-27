package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.HTTP
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.QueryMap

interface BudgetApi {
    @HTTP(method = "DELETE", path = "api/budgets/monthly/{month}", hasBody = true)
    suspend fun archiveMonthlyBudget(@Path("month") month: String,
        @Body request: com.ticketbox.data.remote.dto.BudgetMonthlyArchiveRequestDto): com.ticketbox.data.remote.dto.BudgetMonthlyArchiveResponseDto

    @GET("api/budget/arrangements/{month}")
    suspend fun monthlyArrangement(@Path("month") month: String): com.ticketbox.domain.model.MonthlyArrangementResponse

    @PUT("api/budget/arrangements/{month}")
    suspend fun saveMonthlyArrangement(@Path("month") month: String,
        @Body request: com.ticketbox.domain.model.MonthlyArrangementChange,
        @Header("Idempotency-Key") idempotencyKey: String): com.ticketbox.domain.model.MonthlyArrangement

    @GET("api/budget/arrangements/{month}/history")
    suspend fun monthlyArrangementHistory(@Path("month") month: String,
        @Query("before_version") beforeVersion: Long? = null,
        @Query("limit") limit: Int = 20): com.ticketbox.domain.model.MonthlyArrangementHistory

    @GET("api/budget/advisor/inputs")
    suspend fun trialBudgetAdviceInputs(@Query("month") month: String,
        @Query("timezone") timezone: String?,
        @QueryMap arrangement: Map<String, String>): com.ticketbox.data.remote.dto.BudgetAdviceInputsDto

    @GET("api/budgets/monthly/{month}/history")
    suspend fun budgetHistory(
        @Path("month") month: String,
        @Query("before_version") beforeVersion: Long? = null,
    ): com.ticketbox.data.remote.dto.BudgetHistoryDto

    @GET("api/budget/advisor/inputs")
    suspend fun budgetAdviceInputs(@Query("month") month: String,
        @Query("timezone") timezone: String? = null,
        @Query("home_currency_code") homeCurrencyCode: String? = null): com.ticketbox.data.remote.dto.BudgetAdviceInputsDto

    @GET("api/budgets/monthly")
    suspend fun monthlyBudget(
        @Query("month") month: String,
        @Query("timezone") timezone: String? = null,
    ): BudgetMonthlyDto

    @PUT("api/budgets/monthly/{month}")
    suspend fun updateMonthlyBudget(
        @Path("month") month: String,
        @Body request: BudgetMonthlyUpdateRequestDto,
        @Query("timezone") timezone: String? = null,
        @Header("Idempotency-Key") idempotencyKey: String? = null,
    ): BudgetMonthlyDto

    @POST("api/budget/advise")
    suspend fun budgetAdvise(
        @Body request: com.ticketbox.data.remote.dto.BudgetAdviseRequestDto,
    ): com.ticketbox.data.remote.dto.BudgetAdviseResponseDto
}
