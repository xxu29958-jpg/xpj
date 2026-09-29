package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.NonVpnGetFallbackInterceptor
import com.ticketbox.data.remote.buildApiService
import com.ticketbox.data.remote.portableDownloadInterceptor
import java.io.OutputStream
import java.net.InetAddress
import java.net.ServerSocket
import java.net.Socket
import java.net.SocketException
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicReference
import kotlin.concurrent.thread
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.launch
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import okhttp3.OkHttpClient
import kotlin.test.Test
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class PortableExportCancellationTest {
    @Test fun cancelDuringPreparationClosesBothDirectAndFallbackSockets() {
        assertCancellation(sendPartialBody = false, fallback = false)
        assertCancellation(sendPartialBody = false, fallback = true)
    }

    @Test fun cancelAfterHeadersClosesBothDirectAndFallbackBodyStreams() {
        assertCancellation(sendPartialBody = true, fallback = false)
        assertCancellation(sendPartialBody = true, fallback = true)
    }

    private fun assertCancellation(sendPartialBody: Boolean, fallback: Boolean) = runBlocking {
        val server = ServerSocket(0, 1, InetAddress.getByName("127.0.0.1"))
        val accepted = AtomicReference<Socket?>()
        val serverFailure = AtomicReference<Throwable?>()
        val preparing = CountDownLatch(1)
        val writing = CountDownLatch(1)
        val disconnected = CountDownLatch(1)
        val reader = thread(isDaemon = true, name = "portable-cancel-probe") {
            try {
                server.accept().use { socket ->
                    accepted.set(socket)
                    socket.soTimeout = 5000
                    val input = socket.getInputStream().bufferedReader()
                    while (!input.readLine().isNullOrEmpty()) { /* consume the actual HTTP request */ }
                    preparing.countDown()
                    if (sendPartialBody) {
                        socket.getOutputStream().apply {
                            write("HTTP/1.1 200 OK\r\nContent-Type: application/zip\r\nContent-Length: 16777216\r\nConnection: close\r\n\r\nPART".toByteArray())
                            flush()
                        }
                    }
                    try {
                        if (input.read() == -1) disconnected.countDown()
                    } catch (_: SocketException) { disconnected.countDown() }
                }
            } catch (error: Throwable) { serverFailure.set(error) }
        }
        val session = TestSessionFixture(serverUrl = "http://127.0.0.1:${server.localPort}").apply { saveToken("export-test") }
        val client = OkHttpClient.Builder().addInterceptor(portableDownloadInterceptor())
            .addInterceptor(NonVpnGetFallbackInterceptor(null))
            .addInterceptor { chain ->
                assertTrue(chain.readTimeoutMillis() >= 300000)
                if (fallback) throw SocketException("Binding socket to network 215 failed: EPERM (Operation not permitted)")
                chain.proceed(chain.request())
            }.build()
        val factory = object : ApiServiceFactory {
            override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = buildApiService("$baseUrl/", client)
        }
        val repo = PortableExportRepository(testApiServiceProvider(factory, session))
        var reportedComplete = false
        val saving = launch(Dispatchers.Default) {
            val result = repo.download(PortableExportSelection(assertNotNull(repo.currentBinding()), "archived"), {
                object : OutputStream() { override fun write(value: Int) { writing.countDown() } }
            }, {})
            reportedComplete = result.isSuccess
        }
        try {
            assertTrue(preparing.await(3, TimeUnit.SECONDS), "Request must reach the real server: ${serverFailure.get()}")
            if (sendPartialBody) assertTrue(writing.await(3, TimeUnit.SECONDS), "Response must begin streaming before cancellation")
            withTimeout(3000) { saving.cancelAndJoin() }
            assertTrue(disconnected.await(2, TimeUnit.SECONDS), "Cancelled download retained its ${if (fallback) "fallback" else "direct"} socket")
            assertTrue(!reportedComplete)
        } finally {
            saving.cancel(); accepted.get()?.close(); server.close(); reader.join(1000)
            client.connectionPool.evictAll(); client.dispatcher.executorService.shutdownNow()
        }
    }
}
