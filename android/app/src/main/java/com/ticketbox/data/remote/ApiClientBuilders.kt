package com.ticketbox.data.remote

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.BuildConfig
import com.ticketbox.security.SessionTokenStore
import com.ticketbox.security.StoredSessionToken
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.net.Proxy
import java.time.Instant
import java.util.concurrent.TimeUnit

private const val USER_AGENT = "TicketBox/1.0 Android"
private val RETRYABLE_GET_STATUS_CODES = setOf(502, 503, 504)
private const val GET_IO_RETRY_COUNT = 2
private const val GET_IO_RETRY_DELAY_MS = 350L

internal fun buildApiHttpClient(
    routeProvider: BackendNetworkRouteProvider?,
    tokenProvider: () -> String?,
    refreshController: SessionRefreshController?,
    tokenStore: SessionTokenStore?,
): OkHttpClient {
    val clientBuilder = baseClientBuilder()
        .addInterceptor(authInterceptor(tokenProvider, refreshController, tokenStore))
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
    refreshController: SessionRefreshController?,
    tokenStore: SessionTokenStore?,
): Interceptor =
    Interceptor { chain ->
        val requestBuilder = chain.request().newBuilder()
            .header("User-Agent", USER_AGENT)
        val session = tokenStore?.getSessionToken()
        refreshSessionIfNeeded(session, refreshController, chain)
        appendBearerToken(requestBuilder, session?.token ?: tokenProvider())
        val response = chain.proceed(requestBuilder.build())
        clearSessionOnUnauthorized(response, session, tokenStore)
        response
    }

private fun refreshSessionIfNeeded(
    session: StoredSessionToken?,
    refreshController: SessionRefreshController?,
    chain: Interceptor.Chain,
) {
    if (session == null || requestTargetsRefresh(chain)) {
        return
    }
    val now = Instant.now()
    if (!isExpired(session, now)) {
        refreshController?.refreshAsync(now)
    }
}

private fun appendBearerToken(requestBuilder: Request.Builder, token: String?) {
    token?.takeIf { it.isNotBlank() }?.let {
        requestBuilder.header("Authorization", "Bearer $token")
    }
}

private fun clearSessionOnUnauthorized(
    response: Response,
    session: StoredSessionToken?,
    tokenStore: SessionTokenStore?,
) {
    if (response.code == 401 && session != null) {
        tokenStore?.clear()
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
