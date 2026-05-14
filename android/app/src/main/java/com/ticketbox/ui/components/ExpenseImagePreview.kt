package com.ticketbox.ui.components

import android.graphics.BitmapFactory
import android.graphics.ImageDecoder
import android.os.Build
import android.util.Log
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.produceState
import androidx.compose.runtime.remember
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.DpSize
import com.ticketbox.BuildConfig
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import java.nio.ByteBuffer
import kotlin.math.max

private const val MAX_PREVIEW_LONG_SIDE = 2048
private const val MAX_PREVIEW_PIXELS = 4_194_304
private const val MAX_COMPACT_LONG_SIDE = 768
private const val MAX_COMPACT_PIXELS = 786_432

@Composable
fun ExpenseImagePreview(
    image: ProtectedImage?,
    modifier: Modifier = Modifier,
    placeholder: String = "截图已上传",
    contentDescription: String = "账单截图",
    compact: Boolean = false,
    compactSize: DpSize = DpSize(width = 96.dp, height = 128.dp),
    displayHeight: Dp? = null,
) {
    val imageBitmap by produceState<ImageBitmap?>(null, image, compact) {
        value = null
        value = withContext(Dispatchers.Default) {
            decodeProtectedImage(
                image = image,
                maxLongSide = if (compact) MAX_COMPACT_LONG_SIDE else MAX_PREVIEW_LONG_SIDE,
                maxPixels = if (compact) MAX_COMPACT_PIXELS else MAX_PREVIEW_PIXELS,
            )
        }
    }
    val previewAspectRatio = remember(imageBitmap) {
        val bitmap = imageBitmap
        if (bitmap == null || bitmap.height == 0) {
            4f / 5f
        } else {
            (bitmap.width.toFloat() / bitmap.height.toFloat()).coerceIn(0.75f, 1.45f)
        }
    }
    val decodedBitmap = imageBitmap

    if (decodedBitmap == null) {
        Box(
            modifier = modifier
                .then(
                    if (compact) {
                        Modifier.size(compactSize)
                    } else if (displayHeight != null) {
                        Modifier
                            .fillMaxWidth()
                            .height(displayHeight)
                    } else {
                        Modifier
                            .fillMaxWidth()
                            .aspectRatio(4f / 5f)
                    },
                )
                .clip(RoundedCornerShape(12.dp))
                .background(MaterialTheme.colorScheme.surfaceVariant),
            contentAlignment = Alignment.Center,
        ) {
            Text(
                text = placeholder,
                modifier = Modifier.padding(16.dp),
                color = MaterialTheme.colorScheme.onSurfaceVariant,
                style = MaterialTheme.typography.bodyMedium,
            )
        }
        return
    }

    Image(
        bitmap = decodedBitmap,
        contentDescription = contentDescription,
        modifier = modifier
            .then(
                if (compact) {
                    Modifier.size(compactSize)
                } else if (displayHeight != null) {
                    Modifier
                        .fillMaxWidth()
                        .height(displayHeight)
                } else {
                    Modifier
                        .fillMaxWidth()
                        .aspectRatio(previewAspectRatio)
                },
            )
            .clip(RoundedCornerShape(12.dp))
            .background(MaterialTheme.colorScheme.surfaceVariant),
        contentScale = if (compact) ContentScale.Crop else ContentScale.Fit,
    )
}

private fun decodeProtectedImage(
    image: ProtectedImage?,
    maxLongSide: Int,
    maxPixels: Int,
): ImageBitmap? {
    val bytes = image?.bytes ?: return null
    val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
    BitmapFactory.decodeByteArray(bytes, 0, bytes.size, bounds)
    if (bounds.outWidth > 0 && bounds.outHeight > 0) {
        val sampleSize = previewDecodeSampleSize(
            width = bounds.outWidth,
            height = bounds.outHeight,
            maxLongSide = maxLongSide,
            maxPixels = maxPixels,
        )
        val options = BitmapFactory.Options().apply {
            inPreferredConfig = android.graphics.Bitmap.Config.ARGB_8888
            inSampleSize = sampleSize
        }
        BitmapFactory.decodeByteArray(bytes, 0, bytes.size, options)?.let { bitmap ->
            return bitmap.asImageBitmap()
        }
    }

    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.P) {
        runCatching {
            ImageDecoder.decodeBitmap(ImageDecoder.createSource(ByteBuffer.wrap(bytes))) { decoder, info, _ ->
                val sampleSize = previewDecodeSampleSize(
                    width = info.size.width,
                    height = info.size.height,
                    maxLongSide = maxLongSide,
                    maxPixels = maxPixels,
                )
                if (sampleSize > 1) {
                    decoder.setTargetSize(
                        max(1, info.size.width / sampleSize),
                        max(1, info.size.height / sampleSize),
                    )
                }
                decoder.allocator = ImageDecoder.ALLOCATOR_SOFTWARE
            }.asImageBitmap()
        }.getOrNull()?.let { decoded ->
            return decoded
        }
    }

    if (BuildConfig.DEBUG) {
        val header = bytes.take(16).joinToString(" ") { byte ->
            "%02x".format(byte.toInt() and 0xff)
        }
        Log.w(
            "TicketboxImage",
            "Bitmap decode failed: contentType=${image.contentType} bytes=${bytes.size} header=$header",
        )
    }
    return null
}

internal fun previewDecodeSampleSize(
    width: Int,
    height: Int,
    maxLongSide: Int = MAX_PREVIEW_LONG_SIDE,
    maxPixels: Int = MAX_PREVIEW_PIXELS,
): Int {
    if (width <= 0 || height <= 0) return 1
    var sampleSize = 1
    while (
        width / sampleSize > maxLongSide ||
        height / sampleSize > maxLongSide ||
        (width.toLong() / sampleSize) * (height.toLong() / sampleSize) > maxPixels
    ) {
        sampleSize *= 2
    }
    return sampleSize
}
