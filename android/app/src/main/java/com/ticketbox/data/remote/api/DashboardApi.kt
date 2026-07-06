package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.DashboardCardsResponseDto
import com.ticketbox.data.remote.dto.DashboardCardsUpdateRequestDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.PUT
import retrofit2.http.Query

interface DashboardApi {
    @GET("api/dashboard/cards")
    suspend fun dashboardCards(
        @Query("surface") surface: String = "android",
    ): DashboardCardsResponseDto

    @PUT("api/dashboard/cards")
    suspend fun updateDashboardCards(
        @Body request: DashboardCardsUpdateRequestDto,
        @Query("surface") surface: String = "android",
    ): DashboardCardsResponseDto
}
