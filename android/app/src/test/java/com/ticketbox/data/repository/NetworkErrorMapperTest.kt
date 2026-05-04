package com.ticketbox.data.repository

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue
import java.net.SocketTimeoutException
import java.net.UnknownHostException

class NetworkErrorMapperTest {
    @Test
    fun keepsLocalhostMessageUserFriendly() {
        val message = userNetworkMessage(
            error = SocketTimeoutException(),
            serverUrl = "http://127.0.0.1:8000",
        )

        assertEquals("请填写公网服务器地址。", message)
    }

    @Test
    fun keepsDomainResolutionMessageUserFriendly() {
        val message = userNetworkMessage(
            error = UnknownHostException(),
            serverUrl = "https://api.zen70.cn",
        )

        assertEquals("连接不上服务器，请稍后再试。", message)
    }

    @Test
    fun writesTechnicalReasonForLogs() {
        val message = networkDiagnosticMessage(
            error = UnknownHostException(),
            serverUrl = "https://api.zen70.cn",
        )

        assertTrue(message.contains("DNS lookup failed"))
        assertTrue(message.contains("https://api.zen70.cn"))
    }
}
