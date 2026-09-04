package com.ticketbox.ui.appearance.background

import android.content.Context
import android.content.ContextWrapper
import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.net.Uri
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.local.BackgroundImageStore
import java.io.File
import java.nio.file.Files
import org.junit.Assert.assertArrayEquals
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertThrows
import org.junit.Test

class BackgroundImageStoreTest {
    @Test
    fun undecodableCandidateIsRejectedWithoutReplacingExistingImage() {
        val base = InstrumentationRegistry.getInstrumentation().targetContext
        val directory = Files.createTempDirectory(base.cacheDir.toPath(), "background-test-").toFile()
        val context = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        try {
            val store = BackgroundImageStore(context)
            val first = imageFile(directory, "first.png", Color.RED)
            val existing = File(store.copyPickedImageToPrivateStorage(Uri.fromFile(first)))
            val originalBytes = existing.readBytes()
            val bytes = imageFile(directory, "candidate.png", Color.BLUE).readBytes()
            val pixelData = bytes.toString(Charsets.ISO_8859_1).indexOf("IDAT")
            val damaged = File(directory, "incomplete.png").apply {
                // Keep the PNG header intact but invalidate its compressed pixel stream.
                bytes[pixelData + 4] = 0
                bytes[pixelData + 5] = 0
                writeBytes(bytes)
            }
            val bounds = BitmapFactory.Options().apply { inJustDecodeBounds = true }
            BitmapFactory.decodeFile(damaged.absolutePath, bounds)
            assertEquals("Fixture still has valid image dimensions", 4, bounds.outWidth)
            assertNull("Fixture has no decodable pixels", BitmapFactory.decodeFile(damaged.absolutePath))

            assertThrows(IllegalArgumentException::class.java) {
                store.copyPickedImageToPrivateStorage(Uri.fromFile(damaged))
            }

            assertArrayEquals(originalBytes, existing.readBytes())
            assertEquals(listOf(existing.name), File(directory, "backgrounds").listFiles()!!.map { it.name })
        } finally {
            directory.deleteRecursively()
        }
    }

    @Test
    fun selectingAnotherImageDoesNotChangeExistingImage() {
        val base = InstrumentationRegistry.getInstrumentation().targetContext
        val directory = Files.createTempDirectory(base.cacheDir.toPath(), "background-test-").toFile()
        val context = object : ContextWrapper(base) {
            override fun getApplicationContext(): Context = this
            override fun getFilesDir(): File = directory
        }
        try {
            val store = BackgroundImageStore(context)
            val first = imageFile(directory, "first.png", Color.RED)
            val second = imageFile(directory, "second.png", Color.BLUE)
            val existing = File(store.copyPickedImageToPrivateStorage(Uri.fromFile(first)))
            val originalBytes = existing.readBytes()

            store.copyPickedImageToPrivateStorage(Uri.fromFile(second))

            assertArrayEquals("Selecting a candidate must preserve the existing image", originalBytes, existing.readBytes())
        } finally {
            directory.deleteRecursively()
        }
    }

    private fun imageFile(directory: File, name: String, color: Int): File {
        val image = Bitmap.createBitmap(4, 4, Bitmap.Config.ARGB_8888)
        image.eraseColor(color)
        return File(directory, name).also { file ->
            file.outputStream().use { image.compress(Bitmap.CompressFormat.PNG, 100, it) }
            image.recycle()
        }
    }
}
