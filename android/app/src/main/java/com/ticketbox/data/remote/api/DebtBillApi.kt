package com.ticketbox.data.remote.api

import com.ticketbox.data.remote.dto.DebtBillCaptureReceiptDto
import com.ticketbox.data.remote.dto.DebtBillCaptureDto
import com.ticketbox.data.remote.dto.DebtBillCaptureListDto
import com.ticketbox.data.remote.dto.DebtBillParseRequestDto
import com.ticketbox.data.remote.dto.DebtBillParseOutcomeDto
import okhttp3.MultipartBody
import retrofit2.http.Body
import retrofit2.http.GET
import retrofit2.http.Header
import retrofit2.http.Multipart
import retrofit2.http.POST
import retrofit2.http.Part
import retrofit2.http.Path
import retrofit2.http.Query

/** Private source admission and recovery are separate from financial Debt commands. */
interface DebtBillApi {
    @Multipart
    @POST("api/debt-bills")
    suspend fun captureDebtBill(@Part file: MultipartBody.Part,
        @Part("creation_key") creationKey: okhttp3.RequestBody,
        @Header("Idempotency-Key") captureKey: String): DebtBillCaptureReceiptDto

    @GET("api/debt-bills/by-key/{captureKey}")
    suspend fun debtBillByKey(@Path("captureKey") captureKey: String): DebtBillCaptureDto

    @GET("api/debt-bills")
    suspend fun debtBills(@Query("creation_key") creationKey: String? = null,
        @Query("debt_public_id") debtPublicId: String? = null): DebtBillCaptureListDto

    @GET("api/debt-bills/{publicId}/original")
    @retrofit2.http.Streaming
    suspend fun debtBillOriginal(@Path("publicId") publicId: String): okhttp3.ResponseBody

    @POST("api/debt-bills/{publicId}/parse")
    suspend fun parseDebtBillSource(@Path("publicId") publicId: String,
        @Body request: DebtBillParseRequestDto, @Header("Idempotency-Key") key: String): DebtBillParseOutcomeDto

    @POST("api/debt-bills/{publicId}/discard")
    suspend fun discardDebtBill(@Path("publicId") publicId: String,
        @Body request: DebtBillParseRequestDto, @Header("Idempotency-Key") key: String): DebtBillCaptureDto

}
