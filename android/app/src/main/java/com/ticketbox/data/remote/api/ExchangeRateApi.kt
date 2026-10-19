package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.ExchangeRateDto
import com.ticketbox.data.remote.dto.ExchangeRateListDto
import com.ticketbox.data.remote.dto.ExchangeRateRequestDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PUT
import retrofit2.http.Path
import retrofit2.http.Query
import retrofit2.http.POST
import com.ticketbox.data.remote.dto.ReferenceRateRequestDto
import com.ticketbox.data.remote.dto.ReferenceRatesDto

interface ExchangeRateApi {
    @GET("api/exchange-rates/conversion")
    suspend fun convertAmount(@Query("currency_code") currencyCode: String,
        @Query("home_currency_code") homeCurrencyCode: String, @Query("rate_date") rateDate: String,
        @Query("amount") amount: String): com.ticketbox.data.remote.dto.AmountConversionDto

    @GET("api/exchange-rates/reference")
    suspend fun referenceRates(@Query("home_currency_code") homeCurrencyCode: String,
        @Query("currency_code") currencyCode: String? = null, @Query("rate_date") rateDate: String? = null): ReferenceRatesDto

    @POST("api/exchange-rates/reference")
    suspend fun acquireReferenceRates(@Body request: ReferenceRateRequestDto): ReferenceRatesDto

    @GET("api/exchange-rates")
    suspend fun exchangeRates(@Query("currency_code") currencyCode: String? = null,
        @Query("home_currency_code") homeCurrencyCode: String? = null,
        @Query("rate_date") rateDate: String? = null, @Query("limit") limit: Int = 90): ExchangeRateListDto

    @PUT("api/exchange-rates/{currency_code}/{rate_date}")
    suspend fun saveExchangeRate(@Path("currency_code") currencyCode: String,
        @Path("rate_date") rateDate: String, @Body request: ExchangeRateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String): ExchangeRateDto
}
