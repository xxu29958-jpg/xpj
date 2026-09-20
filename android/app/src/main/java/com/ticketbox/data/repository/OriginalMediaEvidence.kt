package com.ticketbox.data.repository

import okio.ByteString.Companion.toByteString

/** Only the strong digest of these response bytes can accompany an explicit human review. */
internal fun reviewedOriginalDigest(bytes: ByteArray, etag: String?): String? {
    val digest = etag?.takeIf { it.startsWith('"') && it.endsWith('"') }?.removeSurrounding("\"")
    return digest?.takeIf { it.isOriginalDigest() && bytes.toByteString().sha256().hex() == it }
}
