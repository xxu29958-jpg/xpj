package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.RecycleBinListResponseDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreRequestDto
import com.ticketbox.data.remote.dto.RecycleBinRestoreResponseDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST

interface RecycleBinApi {
    @GET("api/recycle-bin")
    suspend fun recycleBin(): RecycleBinListResponseDto

    @POST("api/recycle-bin/restore")
    suspend fun restoreRecycleBinItem(
        @Body request: RecycleBinRestoreRequestDto,
    ): RecycleBinRestoreResponseDto
}
