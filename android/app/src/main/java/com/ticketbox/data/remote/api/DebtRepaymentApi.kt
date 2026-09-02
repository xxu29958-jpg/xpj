package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.RepaymentFactListDto
import com.ticketbox.data.remote.dto.RepaymentVoidCreateRequestDto
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.POST
import retrofit2.http.Path
import retrofit2.http.Query

/** Immutable repayment records and corrections, under the existing Debt fact owner. */
interface DebtRepaymentApi {
    @GET("api/debts/{publicId}/repayments")
    suspend fun debtRepayments(
        @Path("publicId") publicId: String,
        @Query("page") page: Int,
    ): RepaymentFactListDto

    @POST("api/debts/{publicId}/repayment-voids")
    suspend fun voidDebtRepayment(
        @Path("publicId") publicId: String,
        @Body request: RepaymentVoidCreateRequestDto,
        @Header("Idempotency-Key") idempotencyKey: String?,
    ): DebtDto
}
