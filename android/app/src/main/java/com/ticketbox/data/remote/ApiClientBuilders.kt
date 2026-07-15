package com.ticketbox.data.remote

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.BuildConfig
import com.ticketbox.security.RequestAuthSnapshot
import com.ticketbox.security.SessionCredentialRotator
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
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
        .add(KotlinJsonAdapterFactory())
        .build()

    return Retrofit.Builder()
        .baseUrl(normalizedBaseUrl)
        .client(client)
        .addConverterFactory(MoshiConverterFactory.create(moshi))
        .build()
        .create(ApiService::class.java)
}
