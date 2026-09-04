package com.ticketbox.ui.components

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.material3.Text
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.design.LocalThemeVisuals
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class AppPaperCardRenderTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun paperCardUsesTheThemePaperSurface() {
        val backdrop = Color.Blue
        var paper by mutableStateOf(Color.Unspecified)

        composeRule.setContent {
            TicketboxTheme(skin = AppSkin.Midnight) {
                paper = LocalThemeVisuals.current.paperCard
                Box(modifier = Modifier.background(backdrop).padding(20.dp)) {
                    AppPaperCard(
                        modifier = Modifier.size(width = 180.dp, height = 96.dp).testTag(CARD_TAG),
                    ) {
                        Text("账面内容")
                    }
                }
            }
        }
        composeRule.waitForIdle()

        val bitmap = composeRule.onNodeWithTag(CARD_TAG).captureToImage().asAndroidBitmap()
        val center = Color(bitmap.getPixel(bitmap.width / 2, bitmap.height / 2))
        val expected = paper.compositeOver(backdrop, APP_PAPER_CARD_DEFAULT_ALPHA)
        assertTrue("paper card center=$center expected=$expected", center.isCloseTo(expected))
    }

    private fun Color.compositeOver(backdrop: Color, alpha: Float): Color = Color(
        red = red * alpha + backdrop.red * (1f - alpha),
        green = green * alpha + backdrop.green * (1f - alpha),
        blue = blue * alpha + backdrop.blue * (1f - alpha),
        alpha = 1f,
    )

    private fun Color.isCloseTo(other: Color): Boolean =
        listOf(red - other.red, green - other.green, blue - other.blue).all { diff ->
            diff > -CHANNEL_TOLERANCE && diff < CHANNEL_TOLERANCE
        }

    private companion object {
        const val CARD_TAG = "app_paper_card_under_test"
        const val CHANNEL_TOLERANCE = 5f / 255f
    }
}
