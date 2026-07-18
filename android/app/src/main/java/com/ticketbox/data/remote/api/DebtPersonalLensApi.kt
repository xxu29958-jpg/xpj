package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.DebtListResponseDto
import retrofit2.http.GET

/** Server-authoritative viewer-personal payable and receivable projections. */
interface DebtPersonalLensApi {
    @GET("api/debts/payables")
    suspend fun debtPayables(): DebtListResponseDto

    /**
     * Selected-ledger owner/member receivables plus privacy-redacted cross-ledger member shells,
     * de-duplicated by public id on the server.
     */
    @GET("api/debts/receivables")
    suspend fun debtReceivables(): DebtListResponseDto
}
