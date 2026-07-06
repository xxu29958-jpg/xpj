package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.ServerSettingsDto
import retrofit2.http.GET

interface ServerSettingsApi {
    @GET("api/settings/server")
    suspend fun serverSettings(): ServerSettingsDto
}
