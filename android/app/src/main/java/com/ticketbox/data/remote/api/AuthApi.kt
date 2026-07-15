package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.AuthCheckDto
import com.ticketbox.data.remote.dto.PairRequestDto
import com.ticketbox.data.remote.dto.RefreshSessionResponseDto
import com.ticketbox.data.remote.dto.RefreshSessionRequestDto
import com.ticketbox.data.remote.dto.PairResponseDto
import com.ticketbox.data.remote.dto.StatusPrivateDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.POST

interface AuthApi {
    @GET("api/auth/check")
    suspend fun checkAuth(): AuthCheckDto

    /** server 级私有状态(备份链健康,轴6 备份超龄通知数据源);只要 app token,与 ledger 无关。 */
    @GET("api/status/private")
    suspend fun privateStatus(): StatusPrivateDto

    @POST("api/auth/pair")
    suspend fun pairDevice(@Body request: PairRequestDto): PairResponseDto

    @POST("api/auth/refresh")
    suspend fun refreshSession(@Body request: RefreshSessionRequestDto): RefreshSessionResponseDto
}
