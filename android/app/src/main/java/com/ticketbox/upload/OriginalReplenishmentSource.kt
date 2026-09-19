package com.ticketbox.upload

import android.content.Context
import android.net.Uri
import android.provider.OpenableColumns
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** Admitted original copies must never pass through screenshot scaling, rotation or recompression. */
suspend fun Context.readReplenishmentOriginal(uri: Uri): PreparedUploadImage? = withContext(Dispatchers.IO) {
    val resolver = applicationContext.contentResolver
    val bytes = resolver.openInputStream(uri)?.use { input ->
        val output = java.io.ByteArrayOutputStream()
        val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
        while (true) {
            val count = input.read(buffer)
            if (count < 0) break
            require(output.size().toLong() + count <= MAX_ORIGINAL_FALLBACK_BYTES)
            output.write(buffer, 0, count)
        }
        output.toByteArray()
    } ?: return@withContext null
    if (bytes.isEmpty()) return@withContext null
    val name = resolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use {
        if (it.moveToFirst()) it.getString(0) else null
    } ?: "original"
    PreparedUploadImage(fileName = name.replace(Regex("[\\\\/:*?\"<>|]"), "_"), contentType = resolver.getType(uri),
        bytes = bytes, sourceSizeBytes = bytes.size.toLong())
}
