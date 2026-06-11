package com.ticketbox.data.repository

import com.ticketbox.BuildConfig
import java.io.IOException
import java.io.InterruptedIOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException

fun userNetworkMessage(error: IOException, serverUrl: String?): String {
    val cleanServerUrl = serverUrl?.trim().orEmpty()
    return when {
        isLocalOnlyServerUrl(cleanServerUrl) -> "请填写可在手机上访问的地址。"
        error is SSLHandshakeException -> "当前网络或 VPN 可能拦截了小票夹连接，请稍后重试或切换网络。"
        error is SocketTimeoutException -> "网络响应有点慢，请稍后重试。"
        error is InterruptedIOException -> "当前网络连接超时，可能是 VPN 或弱网影响，请稍后重试。"
        error is UnknownHostException -> "当前网络解析不到小票夹服务，请切换网络后重试。"
        error is ConnectException -> "小票夹服务暂时没有响应，请稍后再试；如果一直失败，请联系服务拥有者。"
        else -> "暂时连不上小票夹，请稍后再试。"
    }
}

fun networkDiagnosticMessage(error: IOException, serverUrl: String?): String {
    val cleanServerUrl = serverUrl?.trim().orEmpty()
    if (isLocalOnlyServerUrl(cleanServerUrl)) {
        return "Local-only server URL is not reachable from a phone."
    }
    return when (error) {
        is UnknownHostException -> "DNS lookup failed for the configured TicketBox service."
        is SSLHandshakeException -> "TLS handshake failed for the configured TicketBox service."
        is SocketTimeoutException -> "Network request timed out for the configured TicketBox service."
        is InterruptedIOException -> "Network request timed out or was interrupted for the configured TicketBox service."
        is ConnectException -> "Connection refused or unreachable for the configured TicketBox service."
        else -> "Network request failed for the configured TicketBox service (${error::class.java.simpleName})"
    }
}

/** Normalize + validate a user-entered server URL. Single source for every
 *  unbound entry path (pairing-code bind AND cold-start invitation join), so
 *  the HTTPS / non-local rules can never fork between the two. */
fun validateServerUrlInput(serverUrl: String): String {
    val normalized = serverUrl.trim().trimEnd('/')
    val allowInternalInsecureBinding = BuildConfig.DEBUG && BuildConfig.SHOW_ADVANCED_TOOLS
    require(normalized.isNotBlank()) { "请输入账本地址。" }
    require(allowInternalInsecureBinding || !isLocalOnlyServerUrl(normalized)) { "请填写可在手机上访问的地址。" }
    require(allowInternalInsecureBinding || normalized.startsWith("https://", ignoreCase = true)) { "请使用 HTTPS 地址。" }
    return normalized
}

fun validateBindingInput(serverUrl: String, pairingCode: String): String {
    val normalized = validateServerUrlInput(serverUrl)
    require(pairingCode.isNotBlank()) { "请输入绑定码。" }
    return normalized
}

fun isLocalOnlyServerUrl(serverUrl: String): Boolean {
    return serverUrl.contains("127.0.0.1") ||
        serverUrl.contains("localhost", ignoreCase = true)
}
