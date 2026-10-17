package com.ticketbox.data.local

import android.content.Context
import android.graphics.BitmapFactory
import android.net.Uri
import java.io.File

class BackgroundImageStore(context: Context) {
    private val appContext = context.applicationContext

    fun copyPickedImageToPrivateStorage(uri: Uri): String {
        val directory = File(appContext.filesDir, "backgrounds")
        check(directory.isDirectory || directory.mkdirs()) { "Cannot create background directory" }
        val target = File.createTempFile("background-", ".image", directory)
        try {
            appContext.contentResolver.openInputStream(uri).use { input ->
                requireNotNull(input) { "Cannot open selected image" }
                target.outputStream().use { output -> input.copyTo(output) }
            }
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(target.absolutePath, bounds)
            require(bounds.outWidth > 0 && bounds.outHeight > 0) { "Selected image cannot be decoded" }
            // Dimensions alone do not prove that the pixel stream is decodable.
            // A sampled decode checks it without allocating a full camera-size bitmap.
            bounds.inJustDecodeBounds = false
            bounds.inSampleSize = (maxOf(bounds.outWidth, bounds.outHeight) / 1024).coerceAtLeast(1)
            requireNotNull(BitmapFactory.decodeFile(target.absolutePath, bounds)) {
                "Selected image cannot be decoded"
            }.recycle()
            return target.absolutePath
        } catch (error: Exception) {
            target.delete()
            throw error
        }
    }

    /**
     * Removes private images left behind by an editor that never applied or cancelled (for
     * example after the process was killed). Only files older than [startedAt] are candidates,
     * so an image imported after the sweep began is never touched; [keep] is the applied one.
     */
    fun deleteStaleExcept(keep: String?, startedAt: Long): Int {
        val directory = File(appContext.filesDir, "backgrounds")
        val kept = keep?.let { File(it).canonicalFile }
        return directory.listFiles().orEmpty()
            .filter { it.isFile && it.canonicalFile != kept && it.lastModified() < startedAt }
            .count { it.delete() }
    }

    fun deleteCustomBackground(path: String): Boolean {
        val directory = File(appContext.filesDir, "backgrounds").canonicalFile
        val image = File(path).canonicalFile
        if (image.parentFile != directory) return false
        return !image.exists() || image.delete()
    }
}
