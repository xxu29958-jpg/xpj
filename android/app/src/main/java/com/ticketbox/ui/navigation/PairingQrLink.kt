package com.ticketbox.ui.navigation

import com.ticketbox.data.repository.validateServerUrlInput
import okhttp3.HttpUrl.Companion.toHttpUrlOrNull

data class PairingQrLink(val serverUrl: String, val pairingCode: String)

/** A scan is editable input for the existing enrollment command, never a session. */
fun parsePairingQrLink(raw: String): PairingQrLink? {
    if (raw.length > 2048) return null
    val url = raw.trim().toHttpUrlOrNull() ?: return null
    if (url.scheme != "https" || url.username.isNotEmpty() || url.password.isNotEmpty() ||
        url.encodedPath != "/web/auth/login" || url.query != null) return null
    val fragment = url.fragment ?: return null
    if (!Regex("pairing=[0-9]{8}").matches(fragment)) return null
    val origin = url.newBuilder().encodedPath("/").fragment(null).build().toString()
    val server = runCatching { validateServerUrlInput(origin) }.getOrNull() ?: return null
    return PairingQrLink(server, fragment.removePrefix("pairing="))
}
