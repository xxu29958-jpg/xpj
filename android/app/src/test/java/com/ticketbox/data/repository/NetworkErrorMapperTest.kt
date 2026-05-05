package com.ticketbox.data.repository

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
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

        assertEquals("暂时连不上小票夹，请稍后再试。", message)
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
    fun rejectsBlankBindingAppToken() {
        val error = assertFailsWith<IllegalArgumentException> {
            validateBindingInput(serverUrl = "https://api.zen70.cn", appToken = " ")
        }

        assertEquals("请输入访问口令。", error.message)
    }
}
