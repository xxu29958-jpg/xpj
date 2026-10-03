package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.ServerSettingsDto
import com.ticketbox.data.remote.dto.AccountProfileDto
import com.ticketbox.data.remote.dto.AccountProfileRenameDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST

interface ServerSettingsApi {
    @GET("api/settings/server")
    suspend fun serverSettings(): ServerSettingsDto

    @GET("api/settings/account")
    suspend fun accountProfile(): AccountProfileDto

    @POST("api/settings/account")
    suspend fun renameAccountProfile(@Body request: AccountProfileRenameDto): AccountProfileDto
}
