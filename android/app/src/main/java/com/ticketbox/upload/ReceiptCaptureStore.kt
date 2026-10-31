package com.ticketbox.upload

import android.content.Context
import android.net.Uri
import androidx.core.content.FileProvider
import java.io.File
import java.util.UUID

/** Private camera staging. The existing upload owner takes its own durable original before release. */
class ReceiptCaptureProvider : FileProvider()

internal class ReceiptCaptureStore(private val context: Context) {
    private val directory get() = File(context.filesDir, "receipt-captures")
    private val authority get() = "${context.packageName}.receipt-camera"

    fun create(id: String): Uri {
        require(UUID.fromString(id).toString() == id)
        check(directory.isDirectory || directory.mkdirs())
        val file = File(directory, "$id.jpg")
        check(file.createNewFile())
        return FileProvider.getUriForFile(context, authority, file)
    }

    fun hasPhoto(uri: Uri): Boolean = ownedFile(uri)?.let { it.isFile && it.length() > 0 } == true

    fun release(uri: Uri) {
        ownedFile(uri)?.delete()
    }

    private fun ownedFile(uri: Uri): File? {
        if (uri.scheme != "content" || uri.authority != authority) return null
        val segments = uri.pathSegments
        if (segments.size != 2 || segments[0] != "captures") return null
        val name = segments[1]
        val id = name.removeSuffix(".jpg")
        if (name != "$id.jpg" || runCatching { UUID.fromString(id).toString() }.getOrNull() != id) return null
        return File(directory, name)
    }
}
