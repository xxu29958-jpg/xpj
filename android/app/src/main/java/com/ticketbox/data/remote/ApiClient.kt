package com.ticketbox.data.remote

import android.content.Context
import android.net.ConnectivityManager
import android.net.Network
import android.net.NetworkCapabilities
import android.util.Log
import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.BuildConfig
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
import java.util.concurrent.TimeUnit

class ApiClient(context: Context? = null) : ApiServiceFactory {
    private companion object {
        const val LOG_TAG = "TicketboxNetwork"
        const val USER_AGENT = "TicketBox/1.0 Android"
        val RETRYABLE_GET_STATUS_CODES = setOf(502, 503, 504)
        const val GET_IO_RETRY_COUNT = 2
        const val GET_IO_RETRY_DELAY_MS = 350L
    }

    private val nonVpnNetworkProvider = context?.applicationContext?.let(::NonVpnNetworkProvider)

    override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService {
        val logging = HttpLoggingInterceptor().apply {
            level = HttpLoggingInterceptor.Level.BASIC
        }
        val directNetwork = nonVpnNetworkProvider
            ?.takeIf { it.hasActiveVpnNetwork() }
            ?.validatedNonVpnNetwork()

        val clientBuilder = OkHttpClient.Builder()
            .retryOnConnectionFailure(true)
            .dns(directNetwork?.let(::NetworkDns) ?: Ipv4FirstDns)
            .proxy(Proxy.NO_PROXY)
            .protocols(listOf(Protocol.HTTP_1_1))
            .connectTimeout(10, TimeUnit.SECONDS)
            .readTimeout(20, TimeUnit.SECONDS)
            .writeTimeout(45, TimeUnit.SECONDS)
            .callTimeout(60, TimeUnit.SECONDS)
            .addInterceptor { chain ->
                val requestBuilder = chain.request().newBuilder()
                    .header("User-Agent", USER_AGENT)
                tokenProvider()?.takeIf { it.isNotBlank() }?.let { token ->
                    requestBuilder.header("Authorization", "Bearer $token")
                }
                chain.proceed(requestBuilder.build())
            }
            .addInterceptor(NonVpnGetFallbackInterceptor(nonVpnNetworkProvider))
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
        directNetwork?.let { network ->
            clientBuilder.socketFactory(network.socketFactory)
            if (BuildConfig.DEBUG) {
                Log.d(LOG_TAG, "Binding TicketBox requests to validated non-VPN network.")
            }
        }
        val client = clientBuilder.build()

        val moshi = Moshi.Builder()
            .add(KotlinJsonAdapterFactory())
            .build()

        return Retrofit.Builder()
            .baseUrl(normalizeBaseUrl(baseUrl))
            .client(client)
            .addConverterFactory(MoshiConverterFactory.create(moshi))
            .build()
            .create(ApiService::class.java)
    }

    private fun normalizeBaseUrl(baseUrl: String): String {
        val trimmed = baseUrl.trim()
        return if (trimmed.endsWith("/")) trimmed else "$trimmed/"
    }
}

internal object Ipv4FirstDns : Dns {
    override fun lookup(hostname: String): List<InetAddress> {
        return preferIpv4First(Dns.SYSTEM.lookup(hostname))
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
    private val retryDelayMs: Long,
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
                attempt += 1
                runCatching { Thread.sleep(retryDelayMs * attempt) }
            }
        }
    }
}

internal fun shouldRetryGetIOException(method: String, attempt: Int, maxRetries: Int): Boolean {
    return method == "GET" && attempt < maxRetries
}

internal class NonVpnGetFallbackInterceptor(
    private val networkProvider: NonVpnNetworkProvider?,
) : Interceptor {
    override fun intercept(chain: Interceptor.Chain): Response {
        val request = chain.request()
        try {
            return chain.proceed(request)
        } catch (defaultNetworkError: IOException) {
            if (request.method != "GET") {
                throw defaultNetworkError
            }
            val network = networkProvider?.validatedNonVpnNetwork() ?: throw defaultNetworkError
            val fallbackClient = OkHttpClient.Builder()
                .retryOnConnectionFailure(true)
                .dns(NetworkDns(network))
                .socketFactory(network.socketFactory)
                .proxy(Proxy.NO_PROXY)
                .protocols(listOf(Protocol.HTTP_1_1))
                .connectTimeout(10, TimeUnit.SECONDS)
                .readTimeout(20, TimeUnit.SECONDS)
                .writeTimeout(45, TimeUnit.SECONDS)
                .callTimeout(60, TimeUnit.SECONDS)
                .build()
            return try {
                fallbackClient.newCall(request).execute()
            } catch (fallbackError: IOException) {
                fallbackError.addSuppressed(defaultNetworkError)
                throw fallbackError
            }
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

internal class NonVpnNetworkProvider(context: Context) {
    private val connectivityManager =
        context.getSystemService(Context.CONNECTIVITY_SERVICE) as ConnectivityManager

    @Suppress("DEPRECATION")
    fun hasActiveVpnNetwork(): Boolean {
        return runCatching {
            connectivityManager.allNetworks.any { network ->
                connectivityManager.getNetworkCapabilities(network)
                    ?.hasTransport(NetworkCapabilities.TRANSPORT_VPN) == true
            }
        }.getOrDefault(false)
    }

    @Suppress("DEPRECATION")
    fun validatedNonVpnNetwork(): Network? {
        return runCatching {
            connectivityManager.allNetworks.firstOrNull { network ->
                val capabilities = connectivityManager.getNetworkCapabilities(network) ?: return@firstOrNull false
                capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_INTERNET) &&
                    capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_VALIDATED) &&
                    capabilities.hasCapability(NetworkCapabilities.NET_CAPABILITY_NOT_VPN)
            }
        }.getOrNull()
    }
}
