package com.ticketbox.data.remote

import com.squareup.moshi.Moshi
import com.ticketbox.data.remote.dto.addExpenseCorrectionWireAdapters
import com.ticketbox.data.remote.dto.addRecurringWireAdapters
import com.ticketbox.data.remote.dto.RuntimeCompatibilityDto
import com.ticketbox.data.remote.dto.RuntimeWriteCompatibility
import com.ticketbox.data.remote.dto.ErrorDto
import com.ticketbox.data.remote.dto.toWriteCompatibility
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.BuildConfig
import com.ticketbox.security.RequestAuthSnapshot
import com.ticketbox.security.SessionCredentialRotator
import okhttp3.Interceptor
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.io.IOException
import java.net.Proxy
import java.util.concurrent.TimeUnit

private const val USER_AGENT = "TicketBox/1.0 Android"
private val RETRYABLE_GET_STATUS_CODES = setOf(502, 503, 504)
private const val GET_IO_RETRY_COUNT = 2
private const val GET_IO_RETRY_DELAY_MS = 350L
internal const val LEDGER_ID_HEADER = "X-Ticketbox-Ledger-ID"
internal const val TICKETBOX_API_VERSION_HEADER = "Ticketbox-Api-Version"
internal const val TICKETBOX_CURRENCY_BINDING_HEADER = "Ticketbox-Currency-Binding"
internal const val CURRENT_TICKETBOX_API_VERSION = "2026-09-06"
internal const val UPLOAD_ORIGINAL_RECEIPT_VERSION = 1
private val MUTATING_HTTP_METHODS = setOf("POST", "PUT", "PATCH", "DELETE")
private val runtimeMoshi = Moshi.Builder()
    .add(KotlinJsonAdapterFactory())
    .build()
private val runtimeCompatibilityAdapter = runtimeMoshi.adapter(RuntimeCompatibilityDto::class.java)
private val runtimeErrorAdapter = runtimeMoshi.adapter(ErrorDto::class.java)

internal fun buildApiHttpClient(
    routeProvider: BackendNetworkRouteProvider?,
    tokenProvider: () -> String?,
    ledgerIdProvider: () -> String?,
    refreshController: SessionRefreshController?,
    credentials: SessionCredentialRotator?,
): OkHttpClient {
    val clientBuilder = baseClientBuilder()
        .addInterceptor(
            authInterceptor(
                tokenProvider,
                ledgerIdProvider,
                refreshController,
                credentials,
            ),
        )
        .addInterceptor(RuntimeNegotiationInterceptor())
        .addInterceptor(NonVpnGetFallbackInterceptor(routeProvider))
        .addInterceptor(GetIoRetryInterceptor(GET_IO_RETRY_COUNT, GET_IO_RETRY_DELAY_MS))
        .addInterceptor(retryableGetStatusInterceptor())
    if (BuildConfig.DEBUG && BuildConfig.SHOW_ADVANCED_TOOLS) {
        clientBuilder.addInterceptor(redactedLoggingInterceptor())
    }
    return clientBuilder.build()
}

private fun baseClientBuilder(): OkHttpClient.Builder =
    OkHttpClient.Builder()
        .retryOnConnectionFailure(true)
        .dns(Ipv4FirstDns)
        .proxy(Proxy.NO_PROXY)
        .protocols(listOf(Protocol.HTTP_1_1))
        .connectTimeout(10, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .writeTimeout(45, TimeUnit.SECONDS)
        .callTimeout(60, TimeUnit.SECONDS)

private fun authInterceptor(
    tokenProvider: () -> String?,
    ledgerIdProvider: () -> String?,
    refreshController: SessionRefreshController?,
    credentials: SessionCredentialRotator?,
): Interceptor =
    Interceptor { chain ->
        val requestBuilder = chain.request().newBuilder()
            .header("User-Agent", USER_AGENT)
        val requestSnapshot = credentials?.let {
            resolveRequestAuthSnapshot(
                credentials = it,
                refreshController = refreshController,
                recoverCredential = !requestTargetsRefresh(chain),
            )
        }
        val token = requestSnapshot?.credential?.token ?: tokenProvider()
        appendBearerToken(requestBuilder, token)
        if (!token.isNullOrBlank()) {
            appendLedgerId(requestBuilder, requestSnapshot?.ledgerId ?: ledgerIdProvider())
        }
        chain.proceed(requestBuilder.build())
    }

private fun resolveRequestAuthSnapshot(
    credentials: SessionCredentialRotator,
    refreshController: SessionRefreshController?,
    recoverCredential: Boolean,
): RequestAuthSnapshot {
    val initial = credentials.requestAuthSnapshot()
        ?: throw IOException("Authenticated session changed before request dispatch.")
    val snapshot = if (recoverCredential && refreshController != null) {
        refreshController.prepareForRequest(initial)
            ?: throw IOException("Authenticated session changed during credential recovery.")
    } else {
        initial
    }
    if (snapshot.credential.token.isBlank() ||
        snapshot.ledgerId.isBlank() ||
        snapshot.sessionGeneration.isBlank() ||
        snapshot.bindingRevision.isBlank()
    ) {
        throw IOException("Authenticated session is incomplete.")
    }
    return snapshot
}

private fun appendBearerToken(requestBuilder: Request.Builder, token: String?) {
    token?.takeIf { it.isNotBlank() }?.let {
        requestBuilder.header("Authorization", "Bearer $token")
    }
}

private fun appendLedgerId(requestBuilder: Request.Builder, ledgerId: String?) {
    ledgerId?.trim()?.takeIf { it.isNotEmpty() }?.let { selectedLedger ->
        requestBuilder.header(LEDGER_ID_HEADER, selectedLedger)
    }
}

internal class RuntimeNegotiationInterceptor : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        // Income forecasts require the declared month and separate expected/scheduled fields.
        // Check their read protocol before Retrofit decodes a response from another epoch.
        val incomeForecastRead = request.method == "GET" && request.url.encodedPath == "/api/income-plans"
        val keyedUpload = request.method == "POST" &&
            request.url.encodedPath.endsWith("/api/app/upload-screenshot") && request.header("Idempotency-Key") != null
        // An API date, including one already attached to this request, does not prove receipt replay support.
        if (!request.requiresRuntimeNegotiation(incomeForecastRead, keyedUpload)) {
            return chain.proceed(request)
        }
        val compatibility = readCompatibility(chain, request)
        if (compatibility != null && compatibility.apiVersion != CURRENT_TICKETBOX_API_VERSION) {
            return incompatibleProtocolResponse(request)
        }
        if (keyedUpload && compatibility?.uploadOriginalReceiptVersion != UPLOAD_ORIGINAL_RECEIPT_VERSION) {
            return incompatibleProtocolResponse(request)
        }
        // A readable forecast does not require writer permission or an activated currency binding.
        if (incomeForecastRead || compatibility == null) return chain.proceed(request)
        // Negotiated evidence identifies this request; the backend still authorizes the write.
        // A blocked capability may have a real binding (configuration drift) or none (adoption).
        val negotiatedRequest = request.newBuilder()
            .header(TICKETBOX_API_VERSION_HEADER, checkNotNull(compatibility.apiVersion))
            .removeHeader(TICKETBOX_CURRENCY_BINDING_HEADER)
        compatibility.requestBinding?.let { negotiatedRequest.header(TICKETBOX_CURRENCY_BINDING_HEADER, it) }
        val response = chain.proceed(negotiatedRequest.build())
        if (response.code == 409 && runCatching {
                runtimeErrorAdapter.fromJson(response.peekBody(64 * 1024).string())?.error
            }.getOrNull() == "currency_binding_revision_conflict"
        ) {
            response.close()
            // Another first money write may activate the binding after our read.
            // The server rejected this command without applying it; keep its intent retryable.
            throw IOException("Currency binding changed; retry with the current binding.")
        }
        return response
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

    private fun Request.requiresRuntimeNegotiation(incomeForecastRead: Boolean, keyedUpload: Boolean): Boolean =
        keyedUpload || ((incomeForecastRead || method in MUTATING_HTTP_METHODS) &&
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

private fun incompatibleProtocolResponse(request: Request): Response =
    Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(409)
        .message("Runtime protocol mismatch")
        .body(runtimeErrorAdapter.toJson(ErrorDto(
            error = "runtime_version_mismatch",
            message = "客户端与此服务器的协议版本不匹配，请更新为配套版本后继续。",
        )).toResponseBody("application/json".toMediaType())).build()

private fun retryableGetStatusInterceptor(): Interceptor =
    Interceptor { chain ->
        val request = chain.request()
        val response = chain.proceed(request)
        if (request.method == "GET" && response.code in RETRYABLE_GET_STATUS_CODES) {
            response.close()
            chain.proceed(request)
        } else {
            response
        }
    }

private fun redactedLoggingInterceptor(): HttpLoggingInterceptor =
    HttpLoggingInterceptor().apply {
        level = HttpLoggingInterceptor.Level.BASIC
        // Never let bearer tokens or session cookies appear in logcat,
        // even when SHOW_ADVANCED_TOOLS unlocks the logging interceptor
        // for debug builds. See docs/architecture/SECURITY.md.
        redactHeader("Authorization")
        redactHeader("Cookie")
        redactHeader("Set-Cookie")
    }

private fun requestTargetsRefresh(chain: Interceptor.Chain): Boolean =
    chain.request().url.encodedPath == "/api/auth/refresh"

internal fun buildApiService(normalizedBaseUrl: String, client: OkHttpClient): ApiService {
    val moshi = Moshi.Builder()
        .addExpenseCorrectionWireAdapters()
        .addRecurringWireAdapters()
        .add(KotlinJsonAdapterFactory())
        .build()

    return Retrofit.Builder()
        .baseUrl(normalizedBaseUrl)
        .client(client)
        .addConverterFactory(MoshiConverterFactory.create(moshi))
        .build()
        .create(ApiService::class.java)
}
