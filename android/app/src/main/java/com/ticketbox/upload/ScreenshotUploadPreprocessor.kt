package com.ticketbox.upload

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.graphics.Matrix
import android.net.Uri
import android.os.SystemClock
import android.provider.OpenableColumns
import androidx.exifinterface.media.ExifInterface
import java.io.ByteArrayOutputStream
import java.io.File
import kotlin.math.max
import kotlin.math.roundToInt

data class PreparedUploadImage(
    val fileName: String,
    val contentType: String?,
    val bytes: ByteArray,
    val sourceSizeBytes: Long,
    val preparationDurationMs: Long = 0L,
    val sourceContext: String? = null,
    val sourceTransforms: List<String> = emptyList(),
)

private const val MAX_UPLOAD_LONG_SIDE = 1600
private const val JPEG_QUALITY = 84
private const val KEEP_ORIGINAL_MAX_BYTES = 450_000L
internal const val MAX_ORIGINAL_FALLBACK_BYTES = 10L * 1024L * 1024L
private const val MAX_SOURCE_SNAPSHOT_BYTES = 256L * 1024L * 1024L

fun Context.prepareScreenshotUpload(uri: Uri): PreparedUploadImage? {
    val startedAt = SystemClock.elapsedRealtime()
    val metadata = readUploadMetadata(uri)
    val snapshot = File.createTempFile("screenshot-source-", ".image", cacheDir)
    try {
        // A document provider may return different revisions on successive opens.
        // Freeze once on disk, retaining support for photos larger than the upload fallback limit.
        if (!copySourceSnapshot(uri, snapshot)) return null
        val stableUri = Uri.fromFile(snapshot)
        val context = readImageSourceContext(stableUri, galleryUri = uri)
        return prepareScreenshotUploadImage(stableUri, metadata.copy(sizeBytes = snapshot.length()),
            context.optInt("orientation", 1))?.let { prepared ->
            prepared.withSourceContext(context).copy(preparationDurationMs = SystemClock.elapsedRealtime() - startedAt)
        }
    } finally {
        snapshot.delete()
    }
}

private fun Context.copySourceSnapshot(uri: Uri, snapshot: File): Boolean {
    val input = contentResolver.openInputStream(uri) ?: return false
    return input.use { source ->
        snapshot.outputStream().use { output ->
            val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
            var total = 0L
            while (true) {
                val count = source.read(buffer)
                if (count < 0) break
                total += count
                if (total > MAX_SOURCE_SNAPSHOT_BYTES) return false
                output.write(buffer, 0, count)
            }
            total > 0
        }
    }
}

private fun Context.prepareScreenshotUploadImage(uri: Uri, metadata: UploadMetadata, orientation: Int): PreparedUploadImage? {
    val bounds = readImageBounds(uri)
    if (bounds == null) {
        return readOriginalUpload(uri, metadata)
    }

    val longSide = max(bounds.width, bounds.height)
    if (
        metadata.sizeBytes in 1..KEEP_ORIGINAL_MAX_BYTES &&
        longSide <= MAX_UPLOAD_LONG_SIDE &&
        metadata.contentType in setOf("image/jpeg", "image/png", "image/webp")
    ) {
        return readOriginalUpload(uri, metadata)
    }

    val decoded = decodeSampledBitmap(uri, bounds, orientation) ?: return readOriginalUpload(uri, metadata)
    val sampled = decoded.bitmap
    val normalized = scaleToLongSide(sampled, MAX_UPLOAD_LONG_SIDE)
    if (normalized !== sampled) {
        sampled.recycle()
    }

    val output = ByteArrayOutputStream()
    val resized = max(normalized.width, normalized.height) != longSide
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
        sourceTransforms = buildList {
            add("transcoded")
            if (resized) add("resized")
            if (decoded.orientationApplied) add("orientation_applied")
        },
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

private fun Context.decodeSampledBitmap(uri: Uri, bounds: ImageBounds, orientation: Int): OrientedScreenshot? {
    val options = BitmapFactory.Options().apply {
        inSampleSize = calculateSampleSize(bounds)
        inPreferredConfig = Bitmap.Config.ARGB_8888
    }
    val decoded = contentResolver.openInputStream(uri)?.use { input ->
        BitmapFactory.decodeStream(input, null, options)
    }
    // BitmapFactory ignores EXIF orientation; ImageDecoder honours it on
    // Android 28+. Apply EXIF rotation here so that photos captured in
    // portrait orientation are uploaded right-side up. PNG/WebP typically
    // carry no EXIF tag, so the matrix is identity and returns the source.
    return decoded?.let { orientScreenshotBitmap(it, orientation) }
        ?: decodeBitmapWithImageDecoder(uri, targetLongSide = MAX_UPLOAD_LONG_SIDE)?.let {
            OrientedScreenshot(it, orientation in 2..8)
        }
}

internal data class OrientedScreenshot(val bitmap: Bitmap, val orientationApplied: Boolean)

internal fun orientScreenshotBitmap(bitmap: Bitmap, orientation: Int,
    rotate: (Bitmap, Matrix) -> Bitmap = { source, matrix ->
        Bitmap.createBitmap(source, 0, 0, source.width, source.height, matrix, true)
    }): OrientedScreenshot {
    val matrix = Matrix()
    when (orientation) {
        ExifInterface.ORIENTATION_ROTATE_90 -> matrix.postRotate(90f)
        ExifInterface.ORIENTATION_ROTATE_180 -> matrix.postRotate(180f)
        ExifInterface.ORIENTATION_ROTATE_270 -> matrix.postRotate(270f)
        ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.postScale(-1f, 1f)
        ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.postScale(1f, -1f)
        ExifInterface.ORIENTATION_TRANSPOSE -> {
            matrix.postRotate(90f); matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_TRANSVERSE -> {
            matrix.postRotate(270f); matrix.postScale(-1f, 1f)
        }
        else -> return OrientedScreenshot(bitmap, false)
    }
    val rotated = runCatching {
        rotate(bitmap, matrix)
    }.getOrNull() ?: return OrientedScreenshot(bitmap, false)
    if (rotated !== bitmap) bitmap.recycle()
    return OrientedScreenshot(rotated, rotated !== bitmap)
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
    if (metadata.sizeBytes > MAX_ORIGINAL_FALLBACK_BYTES) {
        return null
    }
    val bytes = contentResolver.openInputStream(uri)?.use { input ->
        input.readBytesWithLimit(MAX_ORIGINAL_FALLBACK_BYTES)
    } ?: return null
    return PreparedUploadImage(
        fileName = metadata.fileName.ifBlank { defaultUploadFileName(metadata.contentType) },
        contentType = metadata.contentType,
        bytes = bytes,
        sourceSizeBytes = metadata.sizeBytes.takeIf { it > 0 } ?: bytes.size.toLong(),
    )
}

internal fun java.io.InputStream.readBytesWithLimit(limitBytes: Long): ByteArray? {
    if (limitBytes <= 0) return null
    val output = ByteArrayOutputStream()
    val buffer = ByteArray(DEFAULT_BUFFER_SIZE)
    var total = 0L
    while (true) {
        val read = read(buffer)
        if (read < 0) break
        total += read.toLong()
        if (total > limitBytes) {
            return null
        }
        output.write(buffer, 0, read)
    }
    return output.toByteArray()
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
