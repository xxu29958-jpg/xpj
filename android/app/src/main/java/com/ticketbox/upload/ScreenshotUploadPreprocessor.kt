package com.ticketbox.upload

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.net.Uri
import android.os.SystemClock
import android.provider.OpenableColumns
import java.io.ByteArrayOutputStream
import kotlin.math.max
import kotlin.math.roundToInt

data class PreparedUploadImage(
    val fileName: String,
    val contentType: String?,
    val bytes: ByteArray,
    val sourceSizeBytes: Long,
    val preparationDurationMs: Long = 0L,
)

private const val MAX_UPLOAD_LONG_SIDE = 1600
private const val JPEG_QUALITY = 84
private const val KEEP_ORIGINAL_MAX_BYTES = 450_000L

fun Context.prepareScreenshotUpload(uri: Uri): PreparedUploadImage? {
    val startedAt = SystemClock.elapsedRealtime()
    return prepareScreenshotUploadImage(uri)?.let { prepared ->
        prepared.copy(preparationDurationMs = SystemClock.elapsedRealtime() - startedAt)
    }
}

private fun Context.prepareScreenshotUploadImage(uri: Uri): PreparedUploadImage? {
    val metadata = readUploadMetadata(uri)
    val bounds = readImageBounds(uri)
    if (bounds == null) {
        return readOriginalUpload(uri, metadata)
    }

    val longSide = max(bounds.width, bounds.height)
    if (
        metadata.sizeBytes in 1..KEEP_ORIGINAL_MAX_BYTES &&
        longSide <= MAX_UPLOAD_LONG_SIDE &&
        metadata.contentType in setOf("image/jpeg", "image/png", "image/webp", "image/heic", "image/heif")
    ) {
        return readOriginalUpload(uri, metadata)
    }

    val sampled = decodeSampledBitmap(uri, bounds) ?: return readOriginalUpload(uri, metadata)
    val normalized = scaleToLongSide(sampled, MAX_UPLOAD_LONG_SIDE)
    if (normalized !== sampled) {
        sampled.recycle()
    }

    val output = ByteArrayOutputStream()
    normalized.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, output)
    normalized.recycle()
    val bytes = output.toByteArray()
    if (bytes.isEmpty()) {
        return readOriginalUpload(uri, metadata)
    }

    return PreparedUploadImage(
        fileName = metadata.fileName.toJpegUploadName(),
        contentType = "image/jpeg",
        bytes = bytes,
        sourceSizeBytes = metadata.sizeBytes,
    )
}

private data class UploadMetadata(
    val fileName: String,
    val contentType: String?,
    val sizeBytes: Long,
)

private data class ImageBounds(
    val width: Int,
    val height: Int,
)

private fun Context.readUploadMetadata(uri: Uri): UploadMetadata {
    var displayName: String? = null
    var sizeBytes = -1L
    contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME, OpenableColumns.SIZE), null, null, null)
        ?.use { cursor ->
            if (cursor.moveToFirst()) {
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (nameIndex >= 0) displayName = cursor.getString(nameIndex)
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) sizeBytes = cursor.getLong(sizeIndex)
            }
        }

    val contentType = contentResolver.getType(uri)
    return UploadMetadata(
        fileName = displayName?.trim()?.takeIf { it.isNotBlank() } ?: defaultUploadFileName(contentType),
        contentType = contentType,
        sizeBytes = sizeBytes,
    )
}

private fun Context.readImageBounds(uri: Uri): ImageBounds? {
    val options = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    contentResolver.openInputStream(uri)?.use { input ->
        BitmapFactory.decodeStream(input, null, options)
    }
    if (options.outWidth <= 0 || options.outHeight <= 0) {
        return readImageBoundsWithImageDecoder(uri)
    }
    return ImageBounds(width = options.outWidth, height = options.outHeight)
}

private fun Context.decodeSampledBitmap(uri: Uri, bounds: ImageBounds): Bitmap? {
    val options = BitmapFactory.Options().apply {
        inSampleSize = calculateSampleSize(bounds)
        inPreferredConfig = Bitmap.Config.ARGB_8888
    }
    val decoded = contentResolver.openInputStream(uri)?.use { input ->
        BitmapFactory.decodeStream(input, null, options)
    }
    return decoded ?: decodeBitmapWithImageDecoder(uri, targetLongSide = MAX_UPLOAD_LONG_SIDE)
}

private fun Context.readImageBoundsWithImageDecoder(uri: Uri): ImageBounds? {
    var bounds: ImageBounds? = null
    runCatching {
        ImageDecoder.decodeBitmap(ImageDecoder.createSource(contentResolver, uri)) { decoder, info, _ ->
            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            bounds = ImageBounds(width = info.size.width, height = info.size.height)
            decoder.setTargetSize(1, 1)
        }
    }.getOrNull()?.recycle()
    return bounds
}

private fun Context.decodeBitmapWithImageDecoder(uri: Uri, targetLongSide: Int? = null): Bitmap? {
    return runCatching {
        ImageDecoder.decodeBitmap(ImageDecoder.createSource(contentResolver, uri)) { decoder, info, _ ->
            decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            targetLongSide?.let { maxLongSide ->
                val sourceWidth = info.size.width
                val sourceHeight = info.size.height
                val sourceLongSide = max(sourceWidth, sourceHeight)
                if (sourceLongSide > maxLongSide) {
                    val scale = maxLongSide.toFloat() / sourceLongSide.toFloat()
                    decoder.setTargetSize(
                        (sourceWidth * scale).roundToInt().coerceAtLeast(1),
                        (sourceHeight * scale).roundToInt().coerceAtLeast(1),
                    )
                }
            }
        }
    }.getOrNull()
}

private fun calculateSampleSize(bounds: ImageBounds): Int {
    var sampleSize = 1
    var width = bounds.width
    var height = bounds.height
    while (max(width, height) / 2 >= MAX_UPLOAD_LONG_SIDE) {
        sampleSize *= 2
        width /= 2
        height /= 2
    }
    return sampleSize
}

private fun scaleToLongSide(bitmap: Bitmap, maxLongSide: Int): Bitmap {
    val longSide = max(bitmap.width, bitmap.height)
    if (longSide <= maxLongSide) return bitmap

    val scale = maxLongSide.toFloat() / longSide.toFloat()
    val targetWidth = (bitmap.width * scale).roundToInt().coerceAtLeast(1)
    val targetHeight = (bitmap.height * scale).roundToInt().coerceAtLeast(1)
    return Bitmap.createScaledBitmap(bitmap, targetWidth, targetHeight, true)
}

private fun Context.readOriginalUpload(uri: Uri, metadata: UploadMetadata): PreparedUploadImage? {
    val bytes = contentResolver.openInputStream(uri)?.use { input -> input.readBytes() } ?: return null
    return PreparedUploadImage(
        fileName = metadata.fileName.ifBlank { defaultUploadFileName(metadata.contentType) },
        contentType = metadata.contentType,
        bytes = bytes,
        sourceSizeBytes = metadata.sizeBytes.takeIf { it > 0 } ?: bytes.size.toLong(),
    )
}

private fun String.toJpegUploadName(): String {
    val cleanName = trim().ifBlank { "ticketbox-screenshot" }
    val baseName = cleanName.substringBeforeLast('.', cleanName).ifBlank { "ticketbox-screenshot" }
    return "$baseName-ticketbox.jpg"
}

private fun defaultUploadFileName(contentType: String?): String {
    val extension = when (contentType?.lowercase()) {
        "image/png" -> "png"
        "image/webp" -> "webp"
        "image/heic", "image/heif" -> "heic"
        else -> "jpg"
    }
    return "ticketbox-screenshot.$extension"
}
