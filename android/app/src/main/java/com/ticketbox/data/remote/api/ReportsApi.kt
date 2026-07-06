package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.LifestyleStatsDto
import com.ticketbox.data.remote.dto.MonthlyStatsDto
import retrofit2.http.GET
import retrofit2.http.Query

interface ReportsApi {
    @GET("api/stats/monthly")
    suspend fun monthlyStats(
        @Query("month") month: String? = null,
        @Query("tag") tag: String? = null,
        @Query("timezone") timezone: String? = null,
    ): MonthlyStatsDto

    @GET("api/stats/lifestyle")
    suspend fun lifestyleStats(
        @Query("month") month: String? = null,
        @Query("timezone") timezone: String? = null,
    ): LifestyleStatsDto
}
