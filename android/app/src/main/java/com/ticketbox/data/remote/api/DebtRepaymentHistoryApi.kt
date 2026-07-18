package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.RepaymentFactListResponseDto
import retrofit2.http.GET
import retrofit2.http.Path
import retrofit2.http.Query

/** Bounded, canonical repayment-fact history reads for one debt. */
interface DebtRepaymentHistoryApi {
    @GET("api/debts/{publicId}/repayments")
    suspend fun debtRepayments(
        @Path("publicId") publicId: String,
        @Query("page") page: Int,
        @Query("page_size") pageSize: Int,
    ): RepaymentFactListResponseDto
}
