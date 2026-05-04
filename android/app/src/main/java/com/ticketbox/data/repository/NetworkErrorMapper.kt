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
        "连接不上服务器，请稍后再试。"
    }
}

fun networkDiagnosticMessage(error: IOException, serverUrl: String?): String {
    val cleanServerUrl = serverUrl?.trim().orEmpty()
    if (isLocalOnlyServerUrl(cleanServerUrl)) {
        return "Local-only server URL is not reachable from a phone: $cleanServerUrl"
    }
    return when (error) {
        is UnknownHostException -> "DNS lookup failed for server URL: $cleanServerUrl"
        is SSLHandshakeException -> "TLS handshake failed for server URL: $cleanServerUrl"
        is SocketTimeoutException -> "Network request timed out for server URL: $cleanServerUrl"
        is ConnectException -> "Connection refused or unreachable for server URL: $cleanServerUrl"
        else -> "Network request failed for server URL: $cleanServerUrl (${error::class.java.simpleName})"
    }
}

fun isLocalOnlyServerUrl(serverUrl: String): Boolean {
    return serverUrl.contains("127.0.0.1") ||
        serverUrl.contains("localhost", ignoreCase = true)
}
