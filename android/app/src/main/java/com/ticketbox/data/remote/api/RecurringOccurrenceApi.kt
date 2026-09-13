package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.Path
import retrofit2.http.PUT

interface RecurringOccurrenceApi {
    @GET("api/recurring/items/{publicId}/occurrences/{month}")
    suspend fun recurringOccurrence(
        @Path("publicId") publicId: String,
        @Path("month") month: String,
    ): RecurringOccurrenceDto

    @PUT("api/recurring/items/{publicId}/occurrences/{month}")
    suspend fun setRecurringOccurrencePayment(
        @Path("publicId") publicId: String,
        @Path("month") month: String,
        @Body request: RecurringOccurrencePaymentRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String,
    ): RecurringOccurrenceDto
}
