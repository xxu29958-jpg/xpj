package com.ticketbox.data.repository

import com.ticketbox.BuildConfig
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

        assertEquals("请填写可在手机上访问的地址。", message)
    }

    @Test
    fun explainsTlsFailuresAsPossibleNetworkOrVpnInterception() {
        val message = userNetworkMessage(
            error = SSLHandshakeException("connection closed"),
            serverUrl = "https://api.example.com",
        )

        assertTrue(message.contains("VPN"))
        assertTrue(message.contains("切换网络"))
    }

    @Test
    fun keepsDomainResolutionMessageUserFriendly() {
        val message = userNetworkMessage(
            error = UnknownHostException(),
            serverUrl = "https://api.example.com",
        )

        assertEquals("当前网络解析不到小票夹服务，请切换网络后重试。", message)
    }

    @Test
    fun explainsServiceUnreachableWithoutTechnicalDetails() {
        val message = userNetworkMessage(
            error = ConnectException("failed to connect"),
            serverUrl = "https://api.example.com",
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
            serverUrl = "https://api.example.com",
        )

        assertTrue(message.contains("VPN"))
        assertTrue(message.contains("超时"))
    }

    @Test
    fun writesTechnicalReasonForLogs() {
        val message = networkDiagnosticMessage(
            error = UnknownHostException(),
            serverUrl = "https://api.example.com",
        )

        assertTrue(message.contains("DNS lookup failed"))
        assertTrue(!message.contains("https://api.example.com"))
    }

    @Test
    fun normalizesBindingServerUrl() {
        val cases = listOf(
            " https://api.example.com/ " to "https://api.example.com",
            "https://API.EXAMPLE.COM:443" to "https://api.example.com",
            "https://xn--fa-hia.de" to "https://xn--fa-hia.de",
            "https://[2001:0DB8:0:0::1]:8443" to "https://[2001:db8::1]:8443",
        )

        cases.forEach { (input, expected) ->
            assertEquals(
                expected,
                validateBindingInput(serverUrl = input, pairingCode = "123456"),
            )
        }
    }

    @Test
    fun rejectsAmbiguousOrNonOriginBindingServerUrls() {
        val invalid = listOf(
            "https://faß.de",
            "https://ＡＰＩ.example.com",
            "https://%31%32%37.0.0.1",
            "https://[::ffff:192.168.1.10]",
            "https://user:pass@api.example.com",
            "https://API.Example.COM./",
            "https://api.example.com../",
            "https://api.example.com/path",
            "https://api.example.com?next=/web",
            "https://api.example.com#fragment",
            "https://api.example.com:0",
        )

        invalid.forEach { input ->
            val error = assertFailsWith<IllegalArgumentException>(input) {
                validateBindingInput(serverUrl = input, pairingCode = "123456")
            }
            assertEquals("请输入有效的账本地址。", error.message, input)
        }
    }

    @Test
    fun rejectsBlankBindingServerUrl() {
        val error = assertFailsWith<IllegalArgumentException> {
            validateBindingInput(serverUrl = " ", pairingCode = "123456")
        }

        assertEquals("请输入账本地址。", error.message)
    }

    @Test
    fun rejectsLocalOnlyBindingServerUrl() {
        if (allowsDebugLocalDevelopmentBinding()) {
            assertEquals(
                "http://127.0.0.1:8000",
                validateBindingInput(serverUrl = "http://127.0.0.1:8000", pairingCode = "123456"),
            )
        } else {
            val error = assertFailsWith<IllegalArgumentException> {
                validateBindingInput(serverUrl = "http://127.0.0.1:8000", pairingCode = "123456")
            }

            assertEquals("请填写可在手机上访问的地址。", error.message)
        }
    }

    @Test
    fun allowsEmulatorHostUrlForDebugBinding() {
        if (allowsDebugLocalDevelopmentBinding()) {
            assertEquals(
                "http://10.0.2.2:8000",
                validateBindingInput(serverUrl = "http://10.0.2.2:8000", pairingCode = "123456"),
            )
        } else {
            val error = assertFailsWith<IllegalArgumentException> {
                validateBindingInput(serverUrl = "http://10.0.2.2:8000", pairingCode = "123456")
            }

            assertEquals("请填写可在手机上访问的地址。", error.message)
        }
    }

    @Test
    fun rejectsPlainHttpBindingServerUrl() {
        if (allowsInternalInsecureBinding()) {
            assertEquals(
                "http://api.zen70.cn",
                validateBindingInput(serverUrl = "http://api.zen70.cn", pairingCode = "123456"),
            )
        } else {
            val error = assertFailsWith<IllegalArgumentException> {
                validateBindingInput(serverUrl = "http://api.zen70.cn", pairingCode = "123456")
            }

            assertEquals("请使用 HTTPS 地址。", error.message)
        }
    }

    @Test
    fun rejectsBlankBindingPairingCode() {
        val error = assertFailsWith<IllegalArgumentException> {
            validateBindingInput(serverUrl = "https://api.example.com", pairingCode = " ")
        }

        assertEquals("请输入绑定码。", error.message)
    }

    private fun allowsInternalInsecureBinding(): Boolean {
        return BuildConfig.DEBUG && BuildConfig.SHOW_ADVANCED_TOOLS
    }

    private fun allowsDebugLocalDevelopmentBinding(): Boolean {
        return BuildConfig.DEBUG
    }
}
