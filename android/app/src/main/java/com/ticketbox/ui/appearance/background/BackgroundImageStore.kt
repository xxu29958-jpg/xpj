package com.ticketbox.ui.appearance.background

import android.content.Context
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.net.Uri
import com.ticketbox.domain.model.BackgroundCropMode
import java.io.File
import kotlin.math.roundToInt

class BackgroundImageStore(
    context: Context,
) {
    private val appContext = context.applicationContext

    fun copyPickedImageToPrivateStorage(uri: Uri): String {
        val dir = ensureBackgroundDir()
        val target = File(dir, CUSTOM_BACKGROUND_ORIGINAL_FILE)
        val temp = File(dir, "$CUSTOM_BACKGROUND_ORIGINAL_FILE.tmp")

        appContext.contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Cannot open selected image" }
            temp.outputStream().use { output ->
                input.copyTo(output)
            }
        }
        replaceFile(temp = temp, target = target)
        return target.absolutePath
    }

    fun cropPickedImageToPrivateStorage(
        sourcePath: String,
        cropMode: BackgroundCropMode,
    ): String {
        val source = File(sourcePath)
        require(source.isFile && isInsideBackgroundDir(source)) { "Selected image is not in app private storage" }
        val decoded = decodeBitmap(source.absolutePath)
        val cropped = cropPortrait(decoded, cropMode)
        val dir = ensureBackgroundDir()
        val target = File(dir, CUSTOM_BACKGROUND_CROPPED_FILE)
        val temp = File(dir, "$CUSTOM_BACKGROUND_CROPPED_FILE.tmp")
        temp.outputStream().use { output ->
            cropped.compress(Bitmap.CompressFormat.JPEG, JPEG_QUALITY, output)
        }
        replaceFile(temp = temp, target = target)
        if (cropped !== decoded) {
            cropped.recycle()
        }
        decoded.recycle()
        return target.absolutePath
    }

    fun deleteCustomBackground(path: String?) {
        if (path.isNullOrBlank()) return
        runCatching {
            File(path).takeIf { file -> file.isFile && isInsideBackgroundDir(file) }?.delete()
        }
    }

    private fun ensureBackgroundDir(): File {
        val dir = File(appContext.filesDir, BACKGROUND_DIR)
        if (!dir.exists()) {
            dir.mkdirs()
        }
        require(dir.isDirectory) { "Cannot create background directory" }
        return dir
    }

    private fun replaceFile(temp: File, target: File) {
        if (target.exists()) {
            target.delete()
        }
        if (!temp.renameTo(target)) {
            temp.copyTo(target, overwrite = true)
            temp.delete()
        }
    }

    private fun isInsideBackgroundDir(file: File): Boolean {
        val backgroundDir = File(appContext.filesDir, BACKGROUND_DIR).canonicalFile
        val candidate = file.canonicalFile
        return candidate == backgroundDir ||
            candidate.path.startsWith(backgroundDir.path + File.separator)
    }

    private fun decodeBitmap(path: String): Bitmap {
        val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeFile(path, bounds)
        require(bounds.outWidth > 0 && bounds.outHeight > 0) { "Selected image cannot be decoded" }
        val options = BitmapFactory.Options().apply {
            inSampleSize = calculateInSampleSize(
                width = bounds.outWidth,
                height = bounds.outHeight,
                maxSide = MAX_WORKING_SIDE,
            )
        }
        return requireNotNull(BitmapFactory.decodeFile(path, options)) {
            "Selected image cannot be decoded"
        }
    }

    private fun cropPortrait(bitmap: Bitmap, cropMode: BackgroundCropMode): Bitmap {
        val sourceWidth = bitmap.width
        val sourceHeight = bitmap.height
        val targetRatio = TARGET_WIDTH_RATIO / TARGET_HEIGHT_RATIO
        val sourceRatio = sourceWidth.toFloat() / sourceHeight.toFloat()
        val maxCropWidth: Int
        val maxCropHeight: Int

        if (sourceRatio > targetRatio) {
            maxCropHeight = sourceHeight
            maxCropWidth = (sourceHeight * targetRatio).roundToInt().coerceAtMost(sourceWidth)
        } else {
            maxCropWidth = sourceWidth
            maxCropHeight = (sourceWidth / targetRatio).roundToInt().coerceAtMost(sourceHeight)
        }

        // Leave a little composition slack even for exact 9:16 phone screenshots,
        // otherwise Top / Center / Bottom would produce identical backgrounds.
        val cropWidth = (maxCropWidth * COMPOSITION_ZOOM_FACTOR)
            .roundToInt()
            .coerceIn(1, maxCropWidth)
        val cropHeight = (cropWidth / targetRatio)
            .roundToInt()
            .coerceIn(1, maxCropHeight)
        val left = ((sourceWidth - cropWidth) / 2).coerceAtLeast(0)
        val top = when (cropMode) {
            BackgroundCropMode.Top -> 0
            BackgroundCropMode.Center -> ((sourceHeight - cropHeight) / 2).coerceAtLeast(0)
            BackgroundCropMode.Bottom -> (sourceHeight - cropHeight).coerceAtLeast(0)
        }
        return Bitmap.createBitmap(bitmap, left, top, cropWidth, cropHeight)
    }

    private fun calculateInSampleSize(width: Int, height: Int, maxSide: Int): Int {
        var sampleSize = 1
        val largestSide = maxOf(width, height)
        while (largestSide / sampleSize > maxSide) {
            sampleSize *= 2
        }
        return sampleSize.coerceAtLeast(1)
    }

    private companion object {
        const val BACKGROUND_DIR = "backgrounds"
        const val CUSTOM_BACKGROUND_ORIGINAL_FILE = "custom_background_original.jpg"
        const val CUSTOM_BACKGROUND_CROPPED_FILE = "custom_background_cropped.jpg"
        const val JPEG_QUALITY = 92
        const val MAX_WORKING_SIDE = 2400
        const val TARGET_WIDTH_RATIO = 9f
        const val TARGET_HEIGHT_RATIO = 16f
        const val COMPOSITION_ZOOM_FACTOR = 0.94f
    }
}
