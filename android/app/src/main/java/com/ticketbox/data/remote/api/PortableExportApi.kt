package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.PortableDownloadRequest
import com.ticketbox.data.remote.dto.LedgerListResponseDto
import okhttp3.ResponseBody
import retrofit2.Call
import retrofit2.http.GET
import retrofit2.http.Query
import retrofit2.http.Streaming
import retrofit2.http.Tag

interface PortableExportApi {
    @GET("api/exports/ledgers")
    suspend fun portableExportLedgers(): LedgerListResponseDto

    @Streaming
    @GET("api/exports/portable")
    fun portableExport(@Query("ledger_id") ledgerId: String, @Tag download: PortableDownloadRequest): Call<ResponseBody>
}
