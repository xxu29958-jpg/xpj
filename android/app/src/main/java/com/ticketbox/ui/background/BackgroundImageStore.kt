package com.ticketbox.ui.background

import android.content.Context
import android.net.Uri
import java.io.File

class BackgroundImageStore(
    context: Context,
) {
    private val appContext = context.applicationContext

    fun copyPickedImageToPrivateStorage(uri: Uri): String {
        val dir = File(appContext.filesDir, BACKGROUND_DIR)
        if (!dir.exists()) {
            dir.mkdirs()
        }
        require(dir.isDirectory) { "Cannot create background directory" }
        val target = File(dir, CUSTOM_BACKGROUND_FILE)
        val temp = File(dir, "$CUSTOM_BACKGROUND_FILE.tmp")

        appContext.contentResolver.openInputStream(uri).use { input ->
            requireNotNull(input) { "Cannot open selected image" }
            temp.outputStream().use { output ->
                input.copyTo(output)
            }
        }
        if (target.exists()) {
            target.delete()
        }
        if (!temp.renameTo(target)) {
            temp.copyTo(target, overwrite = true)
            temp.delete()
        }

        return target.absolutePath
    }

    fun deleteCustomBackground(path: String?) {
        if (path.isNullOrBlank()) return
        runCatching {
            File(path).takeIf { file -> file.isFile && isInsideBackgroundDir(file) }?.delete()
        }
    }

    private fun isInsideBackgroundDir(file: File): Boolean {
        val backgroundDir = File(appContext.filesDir, BACKGROUND_DIR).canonicalFile
        val candidate = file.canonicalFile
        return candidate == backgroundDir ||
            candidate.path.startsWith(backgroundDir.path + File.separator)
    }

    private companion object {
        const val BACKGROUND_DIR = "backgrounds"
        const val CUSTOM_BACKGROUND_FILE = "custom_background.jpg"
    }
}
