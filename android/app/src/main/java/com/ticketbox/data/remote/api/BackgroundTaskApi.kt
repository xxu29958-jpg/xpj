package com.ticketbox.data.remote.api

import retrofit2.http.GET
import retrofit2.http.POST
import retrofit2.http.Path

interface BackgroundTaskApi {
    // ADR-0030 background tasks
    @GET("api/tasks")
    suspend fun listBackgroundTasks(): com.ticketbox.data.remote.dto.BackgroundTaskListResponseDto

    @GET("api/tasks/{publicId}")
    suspend fun getBackgroundTask(
        @Path("publicId") publicId: String,
    ): com.ticketbox.data.remote.dto.BackgroundTaskDto

    @POST("api/tasks/{publicId}/cancel")
    suspend fun cancelBackgroundTask(
        @Path("publicId") publicId: String,
    ): com.ticketbox.data.remote.dto.BackgroundTaskDto
}
