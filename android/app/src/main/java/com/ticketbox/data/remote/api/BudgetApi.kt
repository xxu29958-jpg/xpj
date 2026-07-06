package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.BudgetMonthlyDto
import com.ticketbox.data.remote.dto.BudgetMonthlyUpdateRequestDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.PUT
import retrofit2.http.Query

interface BudgetApi {
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
    ): BudgetMonthlyDto

    @GET("api/budget/discretionary")
    suspend fun budgetDiscretionary(
        @Query("savings_target_cents") savingsTargetCents: Long = 0L,
        @Query("reserved_buffer_cents") reservedBufferCents: Long = 0L,
    ): com.ticketbox.data.remote.dto.DiscretionaryResponseDto

    @POST("api/budget/advise")
    suspend fun budgetAdvise(
        @Body request: com.ticketbox.data.remote.dto.BudgetAdviseRequestDto,
    ): com.ticketbox.data.remote.dto.BudgetAdviseResponseDto
}
