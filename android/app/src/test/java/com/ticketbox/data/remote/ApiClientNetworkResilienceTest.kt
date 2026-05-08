package com.ticketbox.data.remote

import java.net.InetAddress
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
}
