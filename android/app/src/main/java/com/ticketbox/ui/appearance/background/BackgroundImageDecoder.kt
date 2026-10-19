package com.ticketbox.ui.appearance.background

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Matrix
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.graphics.ImageBitmap
import androidx.compose.ui.graphics.asImageBitmap
import androidx.compose.ui.unit.IntSize
import androidx.exifinterface.media.ExifInterface
import com.ticketbox.domain.model.AppSkin
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

/** One decode serves the photo layer, the editor geometry and the readability veil. */
internal class DecodedBackground(
    val path: String,
    val image: ImageBitmap,
    val profile: BackgroundTonalProfile,
    private val needs: Map<Pair<AppSkin, CanvasTextDemand>, FloatArray>,
) {
    val size: IntSize get() = IntSize(image.width, image.height)

    fun needs(skin: AppSkin, demand: CanvasTextDemand): FloatArray = needs.getValue(skin to demand)
}

/**
 * A configured photo as the shell sees it. [photo] is what can be drawn now (the previous photo
 * stays while a replacement decodes, so applying one does not flash the theme canvas).
 * [reservesWindow] is true from the moment a photo is configured until its decode fails, so page
 * geometry that depends on the photo is laid out once instead of shifting when decoding ends.
 */
internal class BackgroundPhoto(val photo: DecodedBackground?, val reservesWindow: Boolean)

@Composable
internal fun rememberBackgroundImage(path: String?): BackgroundPhoto {
    val cleanPath = path?.takeIf { it.isNotBlank() }
    var decoded by remember { mutableStateOf<Pair<String, DecodedBackground?>?>(null) }
    LaunchedEffect(cleanPath) {
        if (cleanPath == null) {
            // Clearing the background releases the bitmap, not just hides it.
            decoded = null
            return@LaunchedEffect
        }
        if (decoded?.first == cleanPath) return@LaunchedEffect
        val result = withContext(Dispatchers.IO) { decodeBackgroundImage(cleanPath) }
        decoded = cleanPath to result
    }
    val current = decoded
    val failed = current != null && current.first == cleanPath && current.second == null
    return BackgroundPhoto(photo = if (cleanPath == null) null else current?.second, reservesWindow = cleanPath != null && !failed)
}

private fun decodeBackgroundImage(path: String): DecodedBackground? {
    val bounds = BitmapFactory.Options().apply {
        inJustDecodeBounds = true
    }
    BitmapFactory.decodeFile(path, bounds)
    if (bounds.outWidth <= 0 || bounds.outHeight <= 0) {
        return null
    }
    val options = BitmapFactory.Options().apply {
        inSampleSize = calculateInSampleSize(
            width = bounds.outWidth,
            height = bounds.outHeight,
            maxSide = MAX_BACKGROUND_SIDE,
        )
    }
    val decoded = BitmapFactory.decodeFile(path, options) ?: return null
    val upright = decoded.uprightByExif(path)
    val profile = tonalProfile(upright)
    val needs = buildMap {
        for (skin in AppSkin.entries) {
            for (demand in CanvasTextDemand.entries) {
                put(skin to demand, BackgroundReadability.sampleNeeds(profile, canvasVeilColor(skin), canvasTextTarget(skin, demand)))
            }
        }
    }
    return DecodedBackground(path, upright.asImageBitmap(), profile, needs)
}

/**
 * Every decoded pixel is read once and each grid cell keeps its darkest and lightest pixel. An
 * averaged thumbnail would turn a busy texture into flat grey, and a single nearest-neighbour sample
 * per cell can land only on the light stripes of a fine pattern; both would under-protect the text.
 */
private fun tonalProfile(bitmap: Bitmap): BackgroundTonalProfile {
    val longest = maxOf(bitmap.width, bitmap.height)
    val columns = (bitmap.width * PROFILE_SIDE / longest).coerceAtLeast(1)
    val rows = (bitmap.height * PROFILE_SIDE / longest).coerceAtLeast(1)
    val darkest = IntArray(columns * rows)
    val lightest = IntArray(columns * rows)
    val low = FloatArray(columns * rows) { Float.MAX_VALUE }
    val high = FloatArray(columns * rows) { -1f }
    val line = IntArray(bitmap.width)
    for (y in 0 until bitmap.height) {
        bitmap.getPixels(line, 0, bitmap.width, 0, y, bitmap.width, 1)
        val rowStart = y * rows / bitmap.height * columns
        for (x in 0 until bitmap.width) {
            val pixel = line[x]
            val cell = rowStart + x * columns / bitmap.width
            val luminance = encodedLuminance(pixel)
            if (luminance < low[cell]) { low[cell] = luminance; darkest[cell] = pixel }
            if (luminance > high[cell]) { high[cell] = luminance; lightest[cell] = pixel }
        }
    }
    return BackgroundTonalProfile.fromCellExtremes(columns, rows, darkest, lightest)
}

/** Relative luminance for ranking pixels within a cell; the contrast check itself stays exact. */
private fun encodedLuminance(pixel: Int): Float =
    0.2126f * LinearChannel[(pixel shr 16) and 0xFF] + 0.7152f * LinearChannel[(pixel shr 8) and 0xFF] +
        0.0722f * LinearChannel[pixel and 0xFF]

private val LinearChannel = FloatArray(256) { BackgroundReadability.relativeLuminance(it / 255f, 0f, 0f) / 0.2126f }

/**
 * 手机相机照片普遍带 EXIF 方向标记；BitmapFactory 不应用它，直接渲染会横向 /
 * 倒置，且 [BackgroundTransformGeometry] 的 cover 换算会拿到错误宽高比。解码后
 * 统一按 EXIF 转正——renderer 与编辑器共用同一 decode，cover 尺寸语义一致。
 * 采样率按 EXIF 前最长边计算即可，90°/270° 旋转不改变最长边。
 */
private fun Bitmap.uprightByExif(path: String): Bitmap {
    val orientation = runCatching {
        ExifInterface(path).getAttributeInt(
            ExifInterface.TAG_ORIENTATION,
            ExifInterface.ORIENTATION_NORMAL,
        )
    }.getOrDefault(ExifInterface.ORIENTATION_NORMAL)
    val matrix = Matrix()
    when (orientation) {
        ExifInterface.ORIENTATION_FLIP_HORIZONTAL -> matrix.setScale(-1f, 1f)
        ExifInterface.ORIENTATION_ROTATE_180 -> matrix.setRotate(180f)
        ExifInterface.ORIENTATION_FLIP_VERTICAL -> matrix.setScale(1f, -1f)
        ExifInterface.ORIENTATION_TRANSPOSE -> {
            matrix.setRotate(90f)
            matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_ROTATE_90 -> matrix.setRotate(90f)
        ExifInterface.ORIENTATION_TRANSVERSE -> {
            matrix.setRotate(270f)
            matrix.postScale(-1f, 1f)
        }
        ExifInterface.ORIENTATION_ROTATE_270 -> matrix.setRotate(270f)
        else -> return this
    }
    return runCatching {
        Bitmap.createBitmap(this, 0, 0, width, height, matrix, true)
    }.getOrDefault(this)
}

private fun calculateInSampleSize(width: Int, height: Int, maxSide: Int): Int {
    var sampleSize = 1
    val largestSide = maxOf(width, height)
    while (largestSide / sampleSize > maxSide) {
        sampleSize *= 2
    }
    return sampleSize.coerceAtLeast(1)
}

private const val MAX_BACKGROUND_SIDE = 2160
private const val PROFILE_SIDE = 48
