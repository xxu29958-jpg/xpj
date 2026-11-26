package com.ticketbox.data.remote

import com.ticketbox.data.remote.dto.RuntimeCompatibilityDto
import com.ticketbox.data.remote.dto.RuntimeWriteCompatibility
import com.ticketbox.data.remote.dto.ErrorDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.data.remote.dto.MemberRepaymentProposalCreateRequestDto
import com.ticketbox.data.remote.dto.toWriteCompatibility
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.Invocation
import com.squareup.moshi.JsonDataException
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
        if (!request.isBusinessRequest()) return chain.proceed(request)
        val capturedVersion = request.header(TICKETBOX_API_VERSION_HEADER)
        if (capturedVersion != null && capturedVersion != CURRENT_TICKETBOX_API_VERSION) return incompatibleProtocolResponse(request)
        if (request.negotiatesWithoutSelectedLedger()) {
            return chain.proceed(request.newBuilder().header(TICKETBOX_API_VERSION_HEADER, CURRENT_TICKETBOX_API_VERSION).build())
        }

        val response = chain.proceed(compatibilityRequest(request))
        if (response.code == 401 || response.code == 403) return response.newBuilder().request(request).build()
        val compatibility = response.use {
            if (!it.isSuccessful) throw IOException("Runtime compatibility is temporarily unavailable.")
            decodeCompatibility(it.body.string())
        } ?: return incompatibleProtocolResponse(request)
        if (!compatibility.accepts(request)) return incompatibleProtocolResponse(request)
        // A readable forecast does not require writer permission or an activated currency binding.
        return chain.proceed(request.withRuntime(compatibility))
    }

    private fun Request.withRuntime(compatibility: RuntimeWriteCompatibility): Request {
        // Negotiated evidence identifies this request; the backend still authorizes the write.
        // An unchosen installation has no binding; the server returns the Owner action.
        val negotiatedRequest = newBuilder()
            .header(TICKETBOX_API_VERSION_HEADER, CURRENT_TICKETBOX_API_VERSION)
        if (!compatibility.writerVersionAccepted || (method == "GET" && apiPath == "/api/income-plans")) {
            negotiatedRequest.removeHeader(TICKETBOX_CURRENCY_BINDING_HEADER)
        } else if (header(TICKETBOX_CURRENCY_BINDING_HEADER) == null) {
            compatibility.requestBinding?.let { negotiatedRequest.header(TICKETBOX_CURRENCY_BINDING_HEADER, it) }
        }
        // Preserve semantic refusals for the existing command recovery owner.
        // Renegotiating on an IO retry cannot establish the old amount's currency.
        return negotiatedRequest.build()
    }

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

private fun decodeCompatibility(json: String): RuntimeWriteCompatibility? = try {
    runtimeCompatibilityAdapter.fromJson(json)?.toWriteCompatibility()
} catch (_: JsonDataException) {
    null
} catch (_: IOException) {
    // The response body was already read. This exception is a JSON syntax or EOF error.
    null
}

private val Request.apiPath: String
    get() = url.encodedPath.let { it.substring(it.indexOf("/api/").coerceAtLeast(0)) }

private fun Request.isBusinessRequest(): Boolean {
    val path = apiPath
    return header("Authorization") != null && path.startsWith("/api/") &&
        !path.startsWith("/api/auth/") && path != "/api/system/runtime-compatibility"
}

// These operations authorize the account or path ledger independently of the selected ledger.
private fun Request.negotiatesWithoutSelectedLedger(): Boolean {
    val path = apiPath
    return path == "/api/settings/account" || path.matches(Regex("/api/ledgers/[^/]+/name")) ||
        (method == "GET" && (path == "/api/ledgers" || path.startsWith("/api/exports/")))
}

private fun RuntimeWriteCompatibility.accepts(request: Request): Boolean {
    if (!readerVersionAccepted || (request.method in MUTATING_HTTP_METHODS && !writerVersionAccepted)) return false
    val path = request.apiPath
    val keyedUpload = request.method == "POST" && path.endsWith("/api/app/upload-screenshot") &&
        request.header("Idempotency-Key") != null
    return supportsProtocol(request.requiresDebtBillSource(), request.requiresAtomicConfirmation(), path == "/api/payment-captures/batch") &&
        supportsRequiredCapabilities(keyedUpload, request.requiredTimeInput(), Regex("/api/expenses/[^/]+/original(?:/.*)?$").containsMatchIn(path),
            request.isDebtActivityRead(), path.endsWith("/original/attach"))
}

private enum class RuntimeTimeInput { Expense, Repayment }

private fun RuntimeWriteCompatibility.supportsProtocol(debtBillSource: Boolean, atomicConfirmation: Boolean, notificationBatch: Boolean): Boolean =
    (!notificationBatch || supportsNotificationBatch) &&
        (!atomicConfirmation || supportsAtomicConfirmation) &&
        (!debtBillSource || supportsDebtBillSource)

private fun Request.requiresAtomicConfirmation(): Boolean = tag(Invocation::class.java)?.arguments()?.any {
    it is com.ticketbox.data.remote.dto.ExpenseStateTokenRequest && it.changes != null
} == true

private fun Request.requiresDebtBillSource(): Boolean =
    apiPath == "/api/debt-bills" || apiPath.startsWith("/api/debt-bills/") ||
        tag(Invocation::class.java)?.arguments()?.any {
            it is com.ticketbox.data.remote.dto.DebtCreateRequestDto && it.billSource != null
        } == true

private fun RuntimeWriteCompatibility.supportsRequiredCapabilities(uploadReceipt: Boolean, timeInput: RuntimeTimeInput?,
    originalAttachment: Boolean, debtActivityRead: Boolean, firstAttachment: Boolean): Boolean =
    (!uploadReceipt || uploadOriginalReceiptVersion == UPLOAD_ORIGINAL_RECEIPT_VERSION) &&
        (when (timeInput) {
            RuntimeTimeInput.Expense -> supportsAccountingTimeInput
            RuntimeTimeInput.Repayment -> supportsRepaymentTimeInput
            null -> true
        }) &&
        (!originalAttachment || supportsOriginalAttachment) &&
        (!firstAttachment || supportsFirstAttachment) &&
        (!debtActivityRead || debtActivityReadVersion == DEBT_ACTIVITY_READ_VERSION)

/** Inspect Retrofit's typed command, never consume or regenerate the original HTTP body. */
private fun Request.requiredTimeInput(): RuntimeTimeInput? = tag(Invocation::class.java)?.arguments()?.firstNotNullOfOrNull { argument ->
    when (argument) {
        is ExpenseManualCreateRequestDto -> RuntimeTimeInput.Expense.takeIf { argument.timeInput != null }
        is ExpenseUpdateRequest -> RuntimeTimeInput.Expense.takeIf { argument.timeInput != null }
        is com.ticketbox.data.remote.dto.ExpenseStateTokenRequest -> RuntimeTimeInput.Expense.takeIf { argument.changes?.timeInput != null }
        is ExpenseCorrectionRequestDto -> RuntimeTimeInput.Expense.takeIf { argument.timeInput.changed }
        is MemberRepaymentProposalCreateRequestDto -> RuntimeTimeInput.Repayment.takeIf { argument.timeInput != null }
        else -> null
    }
}

private fun Request.isDebtActivityRead(): Boolean =
    method == "GET" && Regex("^/api/debts/[^/]+/activity$").matches(apiPath)

private fun incompatibleProtocolResponse(request: Request): Response =
    Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(409)
        .message("Runtime protocol mismatch")
        .body(runtimeErrorAdapter.toJson(ErrorDto(
            error = "runtime_version_mismatch",
            message = "客户端与此服务器的协议版本不匹配，请更新为配套版本后继续。",
        )).toResponseBody("application/json".toMediaType())).build()
