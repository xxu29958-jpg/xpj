package com.ticketbox.ui.appearance.background

import android.graphics.Bitmap
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.size
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.BackgroundTransform
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.ui.theme.TicketboxTheme
import java.io.File
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class BackgroundCompositionRenderTest {
    @get:Rule val compose = createComposeRule()

    @Test
    fun panningToImageEdgeStillCoversTheWholeViewport() {
        val directory = InstrumentationRegistry.getInstrumentation().targetContext.cacheDir
        val file = File.createTempFile("background-edge-", ".png", directory)
        val image = Bitmap.createBitmap(200, 200, Bitmap.Config.ARGB_8888)
        for (x in 0 until image.width) {
            for (y in 0 until image.height) {
                image.setPixel(x, y, if (x < 100) android.graphics.Color.RED else android.graphics.Color.BLUE)
            }
        }
        file.outputStream().use { image.compress(Bitmap.CompressFormat.PNG, 100, it) }
        image.recycle()
        try {
            val settings = BackgroundSettings().withCustomImage(file.absolutePath).copy(
                transform = BackgroundTransform(offsetX = 1f),
                immersionMode = ImmersionMode.Atmosphere,
                enableParallax = false,
            )
            compose.setContent {
                TicketboxTheme(skin = AppSkin.Paper) {
                    Box(Modifier.size(100.dp, 200.dp).testTag("background")) {
                        TicketboxBackgroundLayer(settings, AppSkin.Paper, SurfaceRole.Pending)
                    }
                }
            }
            compose.waitUntil(timeoutMillis = 5_000) { isBlueAt(0.1f) }
            assertTrue("Panning must reveal source pixels, not move an already-clipped viewport", isBlueAt(0.9f))
        } finally {
            file.delete()
        }
    }

    private fun isBlueAt(fraction: Float): Boolean {
        val bitmap = compose.onNodeWithTag("background").captureToImage().asAndroidBitmap()
        val pixel = bitmap.getPixel((bitmap.width * fraction).toInt(), bitmap.height / 2)
        return android.graphics.Color.blue(pixel) > android.graphics.Color.red(pixel) + 50
    }
}
