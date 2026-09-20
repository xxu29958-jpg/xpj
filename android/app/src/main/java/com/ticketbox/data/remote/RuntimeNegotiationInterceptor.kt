package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.RuntimeCompatibilityDto
import com.ticketbox.data.remote.dto.RuntimeWriteCompatibility
import com.ticketbox.data.remote.dto.ErrorDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.toWriteCompatibility
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.Invocation
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import okhttp3.Interceptor
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import java.io.IOException

private val MUTATING_HTTP_METHODS = setOf("POST", "PUT", "PATCH", "DELETE")
private val runtimeMoshi = Moshi.Builder()
    .add(KotlinJsonAdapterFactory())
    .build()
private val runtimeCompatibilityAdapter = runtimeMoshi.adapter(RuntimeCompatibilityDto::class.java)
private val runtimeErrorAdapter = runtimeMoshi.adapter(ErrorDto::class.java)

internal class RuntimeNegotiationInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        // Income forecasts require the declared month and separate expected/scheduled fields.
        // Check their read protocol before Retrofit decodes a response from another epoch.
        val incomeForecastRead = request.method == "GET" && request.url.encodedPath == "/api/income-plans"
        val keyedUpload = request.method == "POST" &&
            request.url.encodedPath.endsWith("/api/app/upload-screenshot") && request.header("Idempotency-Key") != null
        val accountingTimeInput = request.hasAccountingTimeInput()
        val originalAttachment = Regex("/api/expenses/[^/]+/original(?:/.*)?$").containsMatchIn(request.url.encodedPath)
        val debtActivityRead = request.isDebtActivityRead()
        // An API date, including one already attached to this request, does not prove receipt replay support.
        if (!request.requiresRuntimeNegotiation(
                incomeForecastRead,
                keyedUpload || accountingTimeInput || originalAttachment || debtActivityRead,
            )) {
            return chain.proceed(request)
        }
        val compatibility = readCompatibility(chain, request)
        if (compatibility != null && compatibility.apiVersion != CURRENT_TICKETBOX_API_VERSION) {
            return incompatibleProtocolResponse(request)
        }
        if (!compatibility.supportsRequiredCapabilities(
                keyedUpload,
                accountingTimeInput,
                originalAttachment,
                debtActivityRead,
            )) {
            return incompatibleProtocolResponse(request)
        }
        // A readable forecast does not require writer permission or an activated currency binding.
        if (incomeForecastRead || compatibility == null) return chain.proceed(request)
        // Negotiated evidence identifies this request; the backend still authorizes the write.
        // An unchosen installation has no binding; the server returns the Owner action.
        val negotiatedRequest = request.newBuilder()
            .header(TICKETBOX_API_VERSION_HEADER, checkNotNull(compatibility.apiVersion))
            .removeHeader(TICKETBOX_CURRENCY_BINDING_HEADER)
        compatibility.requestBinding?.let { negotiatedRequest.header(TICKETBOX_CURRENCY_BINDING_HEADER, it) }
        // Preserve semantic refusals for the existing command recovery owner.
        // Renegotiating on an IO retry cannot establish the old amount's currency.
        return chain.proceed(negotiatedRequest.build())
    }

    /** The same runtime query supplies evidence for ordinary writes, income reads and keyed uploads. */
    private fun readCompatibility(chain: Interceptor.Chain, request: Request): RuntimeWriteCompatibility? {
        val response = chain.proceed(compatibilityRequest(request))
        if (!response.isSuccessful) {
            response.close()
            throw IOException("Runtime compatibility is temporarily unavailable.")
        }
        return response.use { runtimeCompatibilityAdapter.fromJson(it.body.string())?.toWriteCompatibility() }
    }

    private fun Request.requiresRuntimeNegotiation(incomeForecastRead: Boolean, requiresCapabilityEvidence: Boolean): Boolean =
        requiresCapabilityEvidence || ((incomeForecastRead || method in MUTATING_HTTP_METHODS) &&
            header("Authorization") != null && !url.encodedPath.startsWith("/api/auth/") &&
            header(TICKETBOX_API_VERSION_HEADER) == null)

    private fun compatibilityRequest(request: Request): Request {
        val url = request.url.newBuilder()
            .encodedPath("/api/system/runtime-compatibility")
            .query(null)
            .build()
        val builder = Request.Builder().url(url).get()
        listOf("Authorization", LEDGER_ID_HEADER, "User-Agent").forEach { name ->
            request.header(name)?.let { value -> builder.header(name, value) }
        }
        return builder.build()
    }
}

private fun RuntimeWriteCompatibility?.supportsRequiredCapabilities(uploadReceipt: Boolean, accountingTime: Boolean,
    originalAttachment: Boolean, debtActivityRead: Boolean): Boolean =
    (!uploadReceipt || this?.uploadOriginalReceiptVersion == UPLOAD_ORIGINAL_RECEIPT_VERSION) &&
        (!accountingTime || this?.supportsAccountingTimeInput == true) &&
        (!originalAttachment || this?.supportsOriginalAttachment == true) &&
        (!debtActivityRead || this?.debtActivityReadVersion == DEBT_ACTIVITY_READ_VERSION)

/** Inspect Retrofit's typed command, never consume or regenerate the original HTTP body. */
private fun Request.hasAccountingTimeInput(): Boolean = tag(Invocation::class.java)?.arguments()?.any { argument ->
    when (argument) {
        is ExpenseManualCreateRequestDto -> argument.timeInput != null
        is ExpenseUpdateRequest -> argument.timeInput != null
        is ExpenseCorrectionRequestDto -> argument.timeInput.changed
        else -> false
    }
} == true

private fun Request.isDebtActivityRead(): Boolean =
    method == "GET" && Regex("^/api/debts/[^/]+/activity$").matches(url.encodedPath)

private fun incompatibleProtocolResponse(request: Request): Response =
    Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(409)
        .message("Runtime protocol mismatch")
        .body(runtimeErrorAdapter.toJson(ErrorDto(
            error = "runtime_version_mismatch",
            message = "客户端与此服务器的协议版本不匹配，请更新为配套版本后继续。",
        )).toResponseBody("application/json".toMediaType())).build()
