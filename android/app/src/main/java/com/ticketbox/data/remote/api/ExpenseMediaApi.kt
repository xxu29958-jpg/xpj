package com.ticketbox.data.remote.api

import okhttp3.ResponseBody
import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Path
import retrofit2.http.Streaming

interface ExpenseMediaApi {
    @GET("api/expenses/{id}/image")
    @Streaming
    suspend fun expenseImage(@Path("id") id: Long): Response<ResponseBody>

    @GET("api/expenses/{id}/thumbnail")
    @Streaming
    suspend fun expenseThumbnail(@Path("id") id: Long): Response<ResponseBody>
}
