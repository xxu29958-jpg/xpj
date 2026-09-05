package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.RuntimeCompatibilityDto
import retrofit2.http.GET

interface RuntimeCompatibilityApi {
    @GET("api/system/runtime-compatibility")
    suspend fun runtimeCompatibility(): RuntimeCompatibilityDto
}
