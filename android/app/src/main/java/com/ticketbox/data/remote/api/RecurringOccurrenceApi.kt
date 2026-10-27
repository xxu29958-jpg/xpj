package com.ticketbox.data.remote.api

import com.ticketbox.domain.model.RecurringOccurrence
import com.ticketbox.domain.model.RecurringOccurrencePaymentRequest
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.PUT
import retrofit2.http.Path

interface RecurringOccurrenceApi {
    @GET("api/recurring/items/{publicId}/occurrences/{month}")
    suspend fun recurringOccurrence(
        @Path("publicId") publicId: String,
        @Path("month") month: String,
    ): RecurringOccurrence

    @PUT("api/recurring/items/{publicId}/occurrences/{month}")
    suspend fun setRecurringOccurrencePayment(
        @Path("publicId") publicId: String,
        @Path("month") month: String,
        @Body request: RecurringOccurrencePaymentRequest,
        @Header("Idempotency-Key") idempotencyKey: String,
    ): RecurringOccurrence
}
