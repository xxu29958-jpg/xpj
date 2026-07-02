package com.ticketbox.data.remote

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.BuildConfig
import com.ticketbox.security.SessionTokenStore
import okhttp3.Dns
import okhttp3.Interceptor
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.logging.HttpLoggingInterceptor
import retrofit2.Retrofit
import retrofit2.converter.moshi.MoshiConverterFactory
import java.io.IOException
import java.net.Inet4Address
import java.net.InetAddress
import java.net.Proxy
import java.net.Socket
import java.net.SocketException
import java.time.Instant
import java.util.concurrent.TimeUnit
import javax.net.SocketFactory

class ApiClient(context: Context? = null) : SessionAwareApiServiceFactory {
    private companion object {
        const val USER_AGENT = "TicketBox/1.0 Android"
        val RETRYABLE_GET_STATUS_CODES = setOf(502, 503, 504)
        const val GET_IO_RETRY_COUNT = 2
        const val GET_IO_RETRY_DELAY_MS = 350L
    }

    private val nonVpnNetworkProvider = context?.applicationContext?.let(::NonVpnNetworkProvider)

    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        return createInternal(baseUrl = baseUrl, tokenProvider = tokenProvider, refreshController = null)
    }

    override fun create(baseUrl: String, tokenStore: SessionTokenStore): ApiService {
        val normalized = normalizeBaseUrl(baseUrl)
        val refreshController = SessionRefreshController(
            baseUrl = normalized,
            tokenStore = tokenStore,
            serviceFactory = { serviceBaseUrl, provider ->
                createInternal(
                    baseUrl = serviceBaseUrl,
                    tokenProvider = provider,
                    refreshController = null,
                )
            },
        )
        return createInternal(
            baseUrl = normalized,
            tokenProvider = { tokenStore.getToken() },
            refreshController = refreshController,
            tokenStore = tokenStore,
        )
    }

    private fun createInternal(
        baseUrl: String,
        tokenProvider: () -> String?,
        refreshController: SessionRefreshController?,
        tokenStore: SessionTokenStore? = null,
    ): ApiService {
        val normalizedBaseUrl = normalizeBaseUrl(baseUrl)
        val routeProvider = nonVpnNetworkProvider
            ?.takeUnless { isLocalDevelopmentBaseUrl(normalizedBaseUrl) }
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
            // Never let bearer tokens or session cookies appear in logcat,
            // even when SHOW_ADVANCED_TOOLS unlocks the logging interceptor
            // for debug builds. See docs/architecture/SECURITY.md.
            redactHeader("Authorization")
            redactHeader("Cookie")
            redactHeader("Set-Cookie")
        }
        val clientBuilder = OkHttpClient.Builder()
            .retryOnConnectionFailure(true)
            .dns(DynamicNetworkDns(routeProvider))
            .socketFactory(DynamicNetworkSocketFactory(routeProvider))
            .proxy(Proxy.NO_PROXY)
            .protocols(listOf(Protocol.HTTP_1_1))
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .writeTimeout(45, TimeUnit.SECONDS)
            .callTimeout(60, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val requestBuilder = chain.request().newBuilder()
                    .header("User-Agent", USER_AGENT)
                val session = tokenStore?.getSessionToken()
                if (session != null && !requestTargetsRefresh(chain)) {
                    val now = Instant.now()
                    if (!isExpired(session, now)) {
                        refreshController?.refreshAsync(now)
                    }
                }
                val token = session?.token ?: tokenProvider()
                token?.takeIf { it.isNotBlank() }?.let {
                    requestBuilder.header("Authorization", "Bearer $token")
                }
                val response = chain.proceed(requestBuilder.build())
                if (response.code == 401 && session != null) {
                    tokenStore.clear()
                }
                response
            }
            .addInterceptor(NonVpnGetFallbackInterceptor(routeProvider))
            .addInterceptor(GetIoRetryInterceptor(GET_IO_RETRY_COUNT, GET_IO_RETRY_DELAY_MS))
            .addInterceptor { chain ->
                val request = chain.request()
                val response = chain.proceed(request)
                if (request.method == "GET" && response.code in RETRYABLE_GET_STATUS_CODES) {
                    response.close()
                    chain.proceed(request)
                } else {
                    response
                }
            }
        if (BuildConfig.DEBUG && BuildConfig.SHOW_ADVANCED_TOOLS) {
            clientBuilder.addInterceptor(logging)
        }
        val client = clientBuilder.build()

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

    private fun requestTargetsRefresh(chain: Interceptor.Chain): Boolean =
        chain.request().url.encodedPath == "/api/auth/refresh"

    private fun normalizeBaseUrl(baseUrl: String): String {
        val trimmed = baseUrl.trim()
        return if (trimmed.endsWith("/")) trimmed else "$trimmed/"
    }
}

internal fun isLocalDevelopmentBaseUrl(baseUrl: String): Boolean {
    val normalized = baseUrl.trim().lowercase()
    return normalized.contains("127.0.0.1") ||
        normalized.contains("localhost") ||
        normalized.contains("10.0.2.2") ||
        normalized.contains("[::1]") ||
        normalized.contains("::1")
}

internal object Ipv4FirstDns : Dns {
    override fun lookup(hostname: String): List<InetAddress> {
        return preferIpv4First(Dns.SYSTEM.lookup(hostname))
    }
}

internal interface BackendNetworkRouteProvider {
    fun activeNonVpnLookup(hostname: String): List<InetAddress>?
    fun activeNonVpnSocketFactory(): SocketFactory?
    fun validatedNonVpnNetwork(): Network?
    fun disableNonVpnRouting()
}

internal class DynamicNetworkDns(
    private val networkProvider: BackendNetworkRouteProvider?,
) : Dns {
    override fun lookup(hostname: String): List<InetAddress> {
        val addresses = networkProvider?.activeNonVpnLookup(hostname)
            ?: Dns.SYSTEM.lookup(hostname)
        return preferIpv4First(addresses)
    }
}

internal class DynamicNetworkSocketFactory(
    private val networkProvider: BackendNetworkRouteProvider?,
    private val defaultFactory: SocketFactory = SocketFactory.getDefault(),
) : SocketFactory() {
    private fun selectedFactory(): SocketFactory {
        return networkProvider?.activeNonVpnSocketFactory() ?: defaultFactory
    }

    override fun createSocket(): Socket {
        return selectedFactory().createSocket()
    }

    override fun createSocket(host: String, port: Int): Socket {
        return selectedFactory().createSocket(host, port)
    }

    override fun createSocket(host: String, port: Int, localHost: InetAddress, localPort: Int): Socket {
        return selectedFactory().createSocket(host, port, localHost, localPort)
    }

    override fun createSocket(host: InetAddress, port: Int): Socket {
        return selectedFactory().createSocket(host, port)
    }

    override fun createSocket(address: InetAddress, port: Int, localAddress: InetAddress, localPort: Int): Socket {
        return selectedFactory().createSocket(address, port, localAddress, localPort)
    }
}

internal fun preferIpv4First(addresses: List<InetAddress>): List<InetAddress> {
    return addresses
        .withIndex()
        .sortedWith(
            compareBy<IndexedValue<InetAddress>> { indexed ->
                if (indexed.value is Inet4Address) 0 else 1
            }.thenBy { indexed -> indexed.index },
        )
        .map { indexed -> indexed.value }
}

internal class GetIoRetryInterceptor(
    private val maxRetries: Int,
    private val baseDelayMs: Long,
    private val randomSource: () -> Double = Math::random,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        var attempt = 0
        while (true) {
            try {
                return chain.proceed(request)
            } catch (error: IOException) {
                if (!shouldRetryGetIOException(request.method, attempt, maxRetries)) {
                    throw error
                }
                val sleepMs = retryBackoffMs(attempt = attempt, baseDelayMs = baseDelayMs, random = randomSource)
                attempt += 1
                // OkHttp Interceptor 必须同步执行——这里没法用 coroutine delay。
                // 但旧 `runCatching` 会吞掉 InterruptedException，导致上游协程取消时
                // 网络线程还会再睡一轮再重试。改为：被中断就把中断状态重新点回来，
                // 并抛出原 IOException，让 Call.cancel() 真正生效。
                try {
                    Thread.sleep(sleepMs)
                } catch (interrupted: InterruptedException) {
                    Thread.currentThread().interrupt()
                    throw error
                }
            }
        }
    }
}

internal fun shouldRetryGetIOException(method: String, attempt: Int, maxRetries: Int): Boolean {
    return method == "GET" && attempt < maxRetries
}

/**
 * Exponential backoff with full jitter, capped — see ENGINEERING_RULES §7
 * "客户端重试使用指数退避 + jitter，且必须有终止条件".
 *
 * `attempt` is the 0-based retry index (0 = first retry, 1 = second, ...).
 * Returns a value in `[base/2, base * 2^attempt]` clamped to `MAX_BACKOFF_MS`,
 * so two clients that fail simultaneously won't lockstep into each other's
 * thundering-herd window. The caller passes a deterministic [random] source
 * in tests.
 */
internal fun retryBackoffMs(
    attempt: Int,
    baseDelayMs: Long,
    random: () -> Double = Math::random,
): Long {
    val safeAttempt = attempt.coerceAtLeast(0)
    val exponential = baseDelayMs.toDouble() * (1L shl safeAttempt.coerceAtMost(10))
    val capped = exponential.coerceAtMost(MAX_RETRY_BACKOFF_MS.toDouble())
    // Full jitter, biased away from 0 so we still pace requests instead of
    // dog-piling immediately when random() returns near zero.
    val jittered = (capped / 2.0) + (capped / 2.0) * random()
    return jittered.toLong().coerceAtLeast(1L)
}

internal const val MAX_RETRY_BACKOFF_MS = 5_000L

internal class NonVpnGetFallbackInterceptor(
    private val networkProvider: BackendNetworkRouteProvider?,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        try {
            return chain.proceed(request)
        } catch (defaultNetworkError: IOException) {
            if (defaultNetworkError.isNetworkSelectionDenied()) {
                networkProvider?.disableNonVpnRouting()
                return executeFallbackCall(
                    request = request,
                    originalError = defaultNetworkError,
                    client = defaultNetworkClient(),
                )
            }
            if (request.method != "GET") {
                throw defaultNetworkError
            }
            val network = networkProvider?.validatedNonVpnNetwork() ?: throw defaultNetworkError
            return executeFallbackCall(
                request = request,
                originalError = defaultNetworkError,
                client = nonVpnNetworkClient(network),
            )
        }
    }

    private fun defaultNetworkClient(): OkHttpClient {
        return baseFallbackClientBuilder()
            .dns(Ipv4FirstDns)
            .socketFactory(SocketFactory.getDefault())
            .build()
    }

    private fun nonVpnNetworkClient(network: Network): OkHttpClient {
        return baseFallbackClientBuilder()
            .dns(NetworkDns(network))
            .socketFactory(network.socketFactory)
            .build()
    }

    private fun baseFallbackClientBuilder(): OkHttpClient.Builder {
        return OkHttpClient.Builder()
            .retryOnConnectionFailure(true)
            .proxy(Proxy.NO_PROXY)
            .protocols(listOf(Protocol.HTTP_1_1))
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .writeTimeout(45, TimeUnit.SECONDS)
            .callTimeout(60, TimeUnit.SECONDS)
    }

    private fun executeFallbackCall(
        request: okhttp3.Request,
        originalError: IOException,
        client: OkHttpClient,
    ): Response {
        return try {
            client.newCall(request).execute()
        } catch (fallbackError: IOException) {
            fallbackError.addSuppressed(originalError)
            throw fallbackError
        }
    }
}

internal class NetworkDns(
    private val network: Network,
) : Dns {
    override fun lookup(hostname: String): List<InetAddress> {
        return preferIpv4First(network.getAllByName(hostname).toList())
    }
}

internal class NonVpnNetworkProvider(context: Context) : BackendNetworkRouteProvider {
    private val connectivityManager =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager
    @Volatile
    private var nonVpnRoutingDisabled = false

    @Suppress("DEPRECATION")
    override fun validatedNonVpnNetwork(): Network? {
        return runCatching {
            val activeNetwork = connectivityManager.activeNetwork
            if (activeNetwork != null && activeNetwork.isValidatedNonVpnNetwork()) {
                activeNetwork
            } else {
                connectivityManager.allNetworks.firstOrNull { network ->
                    network.isValidatedNonVpnNetwork()
                }
            }
        }.getOrNull()
    }

    fun activeNonVpnNetwork(): Network? {
        if (nonVpnRoutingDisabled) {
            return null
        }
        // Some proxy/VPN apps rewrite backend DNS to 198.18.x virtual
        // addresses without reliably exposing TRANSPORT_VPN to the app.
        // Remote backend traffic therefore prefers a validated NOT_VPN
        // network whenever Android exposes one. Local dev URLs opt out
        // before this provider is wired into OkHttp.
        return validatedNonVpnNetwork()
    }

    override fun activeNonVpnLookup(hostname: String): List<InetAddress>? {
        return activeNonVpnNetwork()?.let { network ->
            runCatching {
                network.getAllByName(hostname).toList()
            }.getOrNull()
        }
    }

    override fun activeNonVpnSocketFactory(): SocketFactory? {
        return activeNonVpnNetwork()?.socketFactory
    }

    override fun disableNonVpnRouting() {
        nonVpnRoutingDisabled = true
    }

    private fun Network.isValidatedNonVpnNetwork(): Boolean {
        val capabilities = connectivityManager.getNetworkCapabilities(this) ?: return false
        return capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) &&
            capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
    }
}

internal fun Throwable.isNetworkSelectionDenied(): Boolean {
    return isNetworkSelectionDenied(seen = mutableSetOf())
}

private fun Throwable.isNetworkSelectionDenied(seen: MutableSet<Throwable>): Boolean {
    if (!seen.add(this)) {
        return false
    }
    val message = message.orEmpty()
    if (this is SocketException &&
        message.contains("Binding socket to network") &&
        message.contains("EPERM")
    ) {
        return true
    }
    return cause?.isNetworkSelectionDenied(seen) == true ||
        suppressed.any { error -> error.isNetworkSelectionDenied(seen) }
}
