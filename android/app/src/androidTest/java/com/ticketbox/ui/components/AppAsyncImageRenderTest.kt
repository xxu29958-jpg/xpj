package com.ticketbox.ui.components

import android.graphics.Bitmap
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import com.ticketbox.domain.model.ProtectedImage
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test
import java.io.ByteArrayOutputStream

class AppAsyncImageRenderTest {
    @get:Rule val compose = createComposeRule()

    @Test fun decodedOriginalClearsFallbackAndChangedBytesMustDecodeAgain() {
        val current = mutableStateOf<ProtectedImage?>(null)
        val displayed = mutableListOf<ProtectedImage>()
        val placeholder = "原图尚未打开"
        compose.setContent {
            TicketboxTheme(skin = AppSkin.Default) {
                AppAsyncImage(current.value, presentation = AppAsyncImagePresentation(
                    placeholder, "账单原图", contentScale = ContentScale.Fit),
                    onDisplayed = { displayed.add(it) })
            }
        }
        compose.onNodeWithText(placeholder).assertIsDisplayed()
        val first = image(android.graphics.Color.GREEN)
        compose.runOnIdle { current.value = first }
        compose.waitUntil(5_000) { displayed.size == 1 }
        compose.onNodeWithText(placeholder).assertDoesNotExist()
        assertEquals(first, displayed.single())

        compose.runOnIdle { current.value = ProtectedImage(byteArrayOf(1, 2, 3), "image/png") }
        compose.onNodeWithText(placeholder).assertIsDisplayed()
        compose.waitForIdle()
        assertEquals(listOf(first), displayed)

        val replacement = image(android.graphics.Color.BLUE)
        compose.runOnIdle { current.value = replacement }
        compose.waitUntil(5_000) { displayed.size == 2 }
        compose.onNodeWithText(placeholder).assertDoesNotExist()
        assertEquals(listOf(first, replacement), displayed)
    }

    private fun image(color: Int): ProtectedImage {
        val bitmap = Bitmap.createBitmap(8, 24, Bitmap.Config.ARGB_8888)
        bitmap.eraseColor(color)
        val bytes = ByteArrayOutputStream().use { output ->
            bitmap.compress(Bitmap.CompressFormat.PNG, 100, output)
            output.toByteArray()
        }
        bitmap.recycle()
        return ProtectedImage(bytes, "image/png")
    }
}
