package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.ExchangeRateListDto
import com.ticketbox.domain.model.ExchangeRate
import com.ticketbox.domain.model.ExchangeRateRequest
import com.ticketbox.domain.model.ReferenceRateRequest
import com.ticketbox.domain.model.ReferenceRates
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query

interface ExchangeRateApi {
    @GET("api/exchange-rates/conversion")
    suspend fun convertAmount(@Query("currency_code") currencyCode: String,
        @Query("home_currency_code") homeCurrencyCode: String, @Query("rate_date") rateDate: String,
        @Query("amount") amount: String): com.ticketbox.domain.model.AmountConversion

    @GET("api/exchange-rates/reference")
    suspend fun referenceRates(@Query("home_currency_code") homeCurrencyCode: String,
        @Query("currency_code") currencyCode: String? = null, @Query("rate_date") rateDate: String? = null): ReferenceRates

    @POST("api/exchange-rates/reference")
    suspend fun acquireReferenceRates(@Body request: ReferenceRateRequest): ReferenceRates

    @GET("api/exchange-rates")
    suspend fun exchangeRates(@Query("currency_code") currencyCode: String? = null,
        @Query("home_currency_code") homeCurrencyCode: String? = null,
        @Query("rate_date") rateDate: String? = null, @Query("limit") limit: Int = 90): ExchangeRateListDto

    @PUT("api/exchange-rates/{currency_code}/{rate_date}")
    suspend fun saveExchangeRate(@Path("currency_code") currencyCode: String,
        @Path("rate_date") rateDate: String, @Body request: ExchangeRateRequest,
        @Header("Idempotency-Key") idempotencyKey: String): ExchangeRate
}
