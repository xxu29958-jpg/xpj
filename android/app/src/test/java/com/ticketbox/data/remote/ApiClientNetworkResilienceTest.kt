package com.ticketbox.data.remote

import java.net.InetAddress
import java.net.Socket
import javax.net.SocketFactory
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ApiClientNetworkResilienceTest {
    @Test
    fun preferIpv4FirstKeepsStableOrderWithinEachAddressFamily() {
        val ipv6A = InetAddress.getByName("2001:db8::1")
        val ipv4A = InetAddress.getByName("203.0.113.10")
        val ipv6B = InetAddress.getByName("2001:db8::2")
        val ipv4B = InetAddress.getByName("203.0.113.11")

        val sorted = preferIpv4First(listOf(ipv6A, ipv4A, ipv6B, ipv4B))

        assertEquals(listOf(ipv4A, ipv4B, ipv6A, ipv6B), sorted)
    }

    @Test
    fun retriesGetIoFailuresOnlyWithinConfiguredLimit() {
        assertTrue(shouldRetryGetIOException(method = "GET", attempt = 0, maxRetries = 2))
        assertTrue(shouldRetryGetIOException(method = "GET", attempt = 1, maxRetries = 2))
        assertFalse(shouldRetryGetIOException(method = "GET", attempt = 2, maxRetries = 2))
    }

    @Test
    fun neverRetriesMutatingRequestsAfterIoFailure() {
        assertFalse(shouldRetryGetIOException(method = "POST", attempt = 0, maxRetries = 2))
        assertFalse(shouldRetryGetIOException(method = "PATCH", attempt = 0, maxRetries = 2))
        assertFalse(shouldRetryGetIOException(method = "DELETE", attempt = 0, maxRetries = 2))
    }

    @Test
    fun dynamicSocketFactoryFallsBackToDefaultFactoryWhenNoBypassNetworkExists() {
        val defaultFactory = CountingSocketFactory()
        val factory = DynamicNetworkSocketFactory(networkProvider = null, defaultFactory = defaultFactory)

        factory.createSocket()

        assertEquals(1, defaultFactory.createdSockets)
    }

    @Test
    fun localDevelopmentUrlsDoNotUseVpnBypassRouting() {
        assertTrue(isLocalDevelopmentBaseUrl("http://127.0.0.1:8000"))
        assertTrue(isLocalDevelopmentBaseUrl("http://localhost:8000"))
        assertTrue(isLocalDevelopmentBaseUrl("http://10.0.2.2:8000"))
        assertFalse(isLocalDevelopmentBaseUrl("https://api.example.com"))
    }

    // ENGINEERING_RULES §7: exponential backoff + jitter + termination

    @Test
    fun retryBackoffDoublesPerAttempt() {
        // With random()=1.0 the jitter window collapses to its upper bound,
        // so this isolates the exponential progression: base, 2*base, 4*base.
        val base = 100L
        val a0 = retryBackoffMs(attempt = 0, baseDelayMs = base, random = { 1.0 })
        val a1 = retryBackoffMs(attempt = 1, baseDelayMs = base, random = { 1.0 })
        val a2 = retryBackoffMs(attempt = 2, baseDelayMs = base, random = { 1.0 })
        assertEquals(base, a0)
        assertEquals(base * 2, a1)
        assertEquals(base * 4, a2)
    }

    @Test
    fun retryBackoffJitterStaysInLowerHalf() {
        // random()=0 should yield half the deterministic exponential value,
        // proving jitter is non-zero and biased away from 0 (paces, not piles).
        val base = 200L
        val attempt0Low = retryBackoffMs(attempt = 0, baseDelayMs = base, random = { 0.0 })
        val attempt0High = retryBackoffMs(attempt = 0, baseDelayMs = base, random = { 1.0 })
        assertEquals(base / 2, attempt0Low)
        assertEquals(base, attempt0High)
        assertTrue(attempt0Low < attempt0High)
    }

    @Test
    fun retryBackoffCapsAtCeiling() {
        // High attempt counts must not balloon into minutes-long sleeps.
        val ceilingHit = retryBackoffMs(attempt = 30, baseDelayMs = 100L, random = { 1.0 })
        assertEquals(MAX_RETRY_BACKOFF_MS, ceilingHit)
    }

    @Test
    fun retryBackoffNeverReturnsZero() {
        // Even with the worst-case random() collapse, callers must always
        // Thread.sleep at least 1ms — sleeping 0 in a hot retry loop would
        // spin the CPU.
        val tinyBase = 1L
        val tinyAttempt = retryBackoffMs(attempt = 0, baseDelayMs = tinyBase, random = { 0.0 })
        assertTrue(tinyAttempt >= 1L)
    }
}

private class CountingSocketFactory : SocketFactory() {
    var createdSockets: Int = 0
        private set

    override fun createSocket(): Socket {
        createdSockets += 1
        return Socket()
    }

    override fun createSocket(host: String, port: Int): Socket {
        return createSocket()
    }

    override fun createSocket(host: String, port: Int, localHost: InetAddress, localPort: Int): Socket {
        return createSocket()
    }

    override fun createSocket(host: InetAddress, port: Int): Socket {
        return createSocket()
    }

    override fun createSocket(
        address: InetAddress,
        port: Int,
        localAddress: InetAddress,
        localPort: Int,
    ): Socket {
        return createSocket()
    }
}
