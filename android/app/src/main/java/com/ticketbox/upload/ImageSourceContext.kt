package com.ticketbox.upload

import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri
import android.provider.MediaStore
import androidx.exifinterface.media.ExifInterface
import java.security.MessageDigest
import java.time.Instant
import java.time.LocalDateTime
import java.time.ZoneOffset
import java.time.format.DateTimeFormatter
import java.time.format.ResolverStyle
import org.json.JSONArray
import org.json.JSONObject
import okio.ByteString.Companion.toByteString

/** Metadata describes the outer file, never an embedded transaction or a verified date. */
internal fun Context.readImageSourceContext(uri: Uri): JSONObject {
    val context = JSONObject().put("schema_version", 1)
    val times = JSONArray()
    runCatching {
        contentResolver.openInputStream(uri)?.use { input ->
            val exif = ExifInterface(input)
            val orientation = exif.getAttributeInt(ExifInterface.TAG_ORIENTATION, 0)
            if (orientation in 1..8) context.put("orientation", orientation)
            listOf(
                Triple(ExifInterface.TAG_DATETIME_ORIGINAL, ExifInterface.TAG_OFFSET_TIME_ORIGINAL, "exif_original"),
                Triple(ExifInterface.TAG_DATETIME_DIGITIZED, ExifInterface.TAG_OFFSET_TIME_DIGITIZED, "exif_digitized"),
                Triple(ExifInterface.TAG_DATETIME, ExifInterface.TAG_OFFSET_TIME, "exif_modified"),
            ).forEach { (tag, offsetTag, origin) ->
                exifTime(exif.getAttribute(tag), exif.getAttribute(offsetTag))?.let { value ->
                    times.put(JSONObject().put("origin", origin).put("value", value).put("precision", "second"))
                }
            }
        }
    }
    runCatching {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        contentResolver.openInputStream(uri)?.use { BitmapFactory.decodeStream(it, null, bounds) }
        if (bounds.outWidth > 0 && bounds.outHeight > 0) {
            context.put("original_width", bounds.outWidth).put("original_height", bounds.outHeight)
        }
        originalImageDigest(uri)?.let { context.put("original_sha256", it) }
    }
    appendGalleryTimes(uri, times)
    return context.put("times", times)
}

private fun exifTime(value: String?, offset: String?): String? = runCatching {
    if (value == null) return null
    val formatter = DateTimeFormatter.ofPattern("uuuu:MM:dd HH:mm:ss").withResolverStyle(ResolverStyle.STRICT)
    val local = LocalDateTime.parse(value, formatter)
    if (offset.isNullOrBlank()) local.toString() else local.atOffset(ZoneOffset.of(offset)).toString()
}.getOrNull()

private fun Context.originalImageDigest(uri: Uri): String? = contentResolver.openInputStream(uri)?.use { input ->
    val digest = MessageDigest.getInstance("SHA-256")
    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
    var count = 0L
    while (true) {
        val read = input.read(buffer)
        if (read < 0) break
        count += read
        // Context collection must not add an unbounded full-file read to image preparation.
        if (count > MAX_ORIGINAL_FALLBACK_BYTES) return@use null
        digest.update(buffer, 0, read)
    }
    digest.digest().toByteString().hex()
}

private fun Context.appendGalleryTimes(uri: Uri, times: JSONArray) {
    if (uri.authority != MediaStore.AUTHORITY) return
    runCatching {
        val columns = arrayOf(MediaStore.MediaColumns.DATE_TAKEN, MediaStore.MediaColumns.DATE_MODIFIED)
        contentResolver.query(uri, columns, null, null, null)?.use { cursor ->
            if (!cursor.moveToFirst()) return@use
            columns.forEachIndexed { position, column ->
                val index = cursor.getColumnIndex(column)
                if (index >= 0 && !cursor.isNull(index) && cursor.getLong(index) > 0) {
                    val instant = if (position == 0) Instant.ofEpochMilli(cursor.getLong(index))
                        else Instant.ofEpochSecond(cursor.getLong(index))
                    times.put(JSONObject().put("origin", if (position == 0) "media_store_taken" else "media_store_modified")
                        .put("value", instant.toString()).put("precision", if (position == 0) "millisecond" else "second"))
                }
            }
        }
    }
}

internal fun PreparedUploadImage.withSourceContext(context: JSONObject): PreparedUploadImage {
    val transforms = sourceTransforms.toMutableList()
    if ("transcoded" in transforms && context.optInt("orientation", 1) in 2..8) transforms.add("orientation_applied")
    context.put("upload_sha256", bytes.toByteString().sha256().hex()).put("transforms", JSONArray(transforms))
    return copy(sourceContext = context.toString())
}
