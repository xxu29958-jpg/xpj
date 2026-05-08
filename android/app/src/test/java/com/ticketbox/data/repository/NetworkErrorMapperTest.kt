package com.ticketbox.data.repository

import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import java.io.InterruptedIOException
import javax.net.ssl.SSLHandshakeException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

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
    fun explainsTlsFailuresAsPossibleNetworkOrVpnInterception() {
        val message = userNetworkMessage(
            error = SSLHandshakeException("connection closed"),
            serverUrl = "https://api.zen70.cn",
        )

        assertTrue(message.contains("VPN"))
        assertTrue(message.contains("切换网络"))
    }

    @Test
    fun keepsDomainResolutionMessageUserFriendly() {
        val message = userNetworkMessage(
            error = UnknownHostException(),
            serverUrl = "https://api.zen70.cn",
        )

        assertEquals("当前网络解析不到小票夹服务，请切换网络后重试。", message)
    }

    @Test
    fun explainsServiceUnreachableWithoutTechnicalDetails() {
        val message = userNetworkMessage(
            error = ConnectException("failed to connect"),
            serverUrl = "https://api.zen70.cn",
        )

        assertTrue(message.contains("服务暂时没有响应"))
        assertTrue(message.contains("服务拥有者"))
        assertTrue(!message.contains("127.0.0.1"))
        assertTrue(!message.contains("Tunnel"))
        assertTrue(!message.contains("端口"))
    }

    @Test
    fun explainsInterruptedTimeoutAsWeakNetworkOrVpn() {
        val message = userNetworkMessage(
            error = InterruptedIOException("timeout"),
            serverUrl = "https://api.zen70.cn",
        )

        assertTrue(message.contains("VPN"))
        assertTrue(message.contains("超时"))
    }

    @Test
    fun writesTechnicalReasonForLogs() {
        val message = networkDiagnosticMessage(
            error = UnknownHostException(),
            serverUrl = "https://api.zen70.cn",
        )

        assertTrue(message.contains("DNS lookup failed"))
        assertTrue(!message.contains("https://api.zen70.cn"))
    }

    @Test
    fun normalizesBindingServerUrl() {
        val normalized = validateBindingInput(
            serverUrl = " https://api.zen70.cn/ ",
            appToken = "token",
        )

        assertEquals("https://api.zen70.cn", normalized)
    }

    @Test
    fun rejectsBlankBindingServerUrl() {
        val error = assertFailsWith<IllegalArgumentException> {
            validateBindingInput(serverUrl = " ", appToken = "token")
        }

        assertEquals("请输入服务器地址。", error.message)
    }

    @Test
    fun rejectsLocalOnlyBindingServerUrl() {
        val error = assertFailsWith<IllegalArgumentException> {
            validateBindingInput(serverUrl = "http://127.0.0.1:8000", appToken = "token")
        }

        assertEquals("请填写公网服务器地址。", error.message)
    }

    @Test
    fun rejectsPlainHttpBindingServerUrl() {
        val error = assertFailsWith<IllegalArgumentException> {
            validateBindingInput(serverUrl = "http://api.zen70.cn", appToken = "token")
        }

        assertEquals("请使用 HTTPS 同步地址。", error.message)
    }

    @Test
    fun rejectsBlankBindingAppToken() {
        val error = assertFailsWith<IllegalArgumentException> {
            validateBindingInput(serverUrl = "https://api.zen70.cn", appToken = " ")
        }

        assertEquals("请输入访问口令。", error.message)
    }
}
