package com.ticketbox.data.repository

import java.io.IOException
import java.net.ConnectException
import java.net.SocketTimeoutException
import java.net.UnknownHostException
import javax.net.ssl.SSLHandshakeException

fun userNetworkMessage(error: IOException, serverUrl: String?): String {
    val cleanServerUrl = serverUrl?.trim().orEmpty()
    return if (isLocalOnlyServerUrl(cleanServerUrl)) {
        "请填写公网服务器地址。"
    } else {
        "暂时连不上小票夹，请稍后再试。"
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
        is ConnectException -> "Connection refused or unreachable for the configured TicketBox service."
        else -> "Network request failed for the configured TicketBox service (${error::class.java.simpleName})"
    }
}

fun validateBindingInput(serverUrl: String, appToken: String): String {
    val normalized = serverUrl.trim().trimEnd('/')
    require(normalized.isNotBlank()) { "请输入服务器地址。" }
    require(!isLocalOnlyServerUrl(normalized)) { "请填写公网服务器地址。" }
    require(appToken.isNotBlank()) { "请输入访问口令。" }
    return normalized
}

fun isLocalOnlyServerUrl(serverUrl: String): Boolean {
    return serverUrl.contains("127.0.0.1") ||
        serverUrl.contains("localhost", ignoreCase = true)
}
