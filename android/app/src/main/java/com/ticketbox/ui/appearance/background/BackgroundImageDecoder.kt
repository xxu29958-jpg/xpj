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
import androidx.exifinterface.media.ExifInterface
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext

@Composable
internal fun rememberBackgroundImage(path: String?): ImageBitmap? {
    var image by remember(path) { mutableStateOf<ImageBitmap?>(null) }
    LaunchedEffect(path) {
        image = null
        val cleanPath = path?.takeIf { it.isNotBlank() } ?: return@LaunchedEffect
        image = withContext(Dispatchers.IO) {
            decodeBackgroundImage(cleanPath)
        }
    }
    return image
}

private fun decodeBackgroundImage(path: String): ImageBitmap? {
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
    return decoded.uprightByExif(path).asImageBitmap()
}

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
