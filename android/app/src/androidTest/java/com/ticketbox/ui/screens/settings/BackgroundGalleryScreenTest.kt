package com.ticketbox.ui.screens.settings

import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.DeviceConfigurationOverride
import androidx.compose.ui.test.ForcedSize
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.DpSize
import androidx.compose.ui.unit.dp
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.ui.appearance.BackgroundCatalog
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class BackgroundGalleryScreenTest {
    @get:Rule val compose = createComposeRule()

    @Test fun galleryKeepsNamesAndDescriptionsReadableAndPreviewsTheChosenBackground() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        val background = requireNotNull(BackgroundCatalog.find("paper_warm"))
        val description = context.getString(R.string.appearance_builtin_background_meta,
            context.getString(builtInBackgroundCategoryNameRes(background.category)),
            context.getString(appSkinNameRes(requireNotNull(background.preferredSkin))),
            context.getString(builtInBackgroundDescriptionRes(background)))
        val width = mutableStateOf(320.dp)
        val scale = mutableStateOf(2f)
        val skin = mutableStateOf(AppSkin.Midnight)
        var picked: String? = null
        compose.setContent {
            DeviceConfigurationOverride(DeviceConfigurationOverride.ForcedSize(DpSize(width.value, 900.dp))) {
                CompositionLocalProvider(LocalDensity provides Density(LocalDensity.current.density, scale.value)) {
                    TicketboxTheme(skin = skin.value) {
                        BackgroundGalleryScreen(BackgroundSettings().withBuiltInBackground("paper_warm"),
                            onBack = {}, onPickCustomImage = {}, onRestoreTheme = {},
                            onPreviewBuiltIn = { picked = it.id })
                    }
                }
            }
        }
        for ((viewport, font) in listOf(320.dp to 2f, 393.dp to 1f, 1440.dp to 1f)) {
            compose.runOnIdle { width.value = viewport; scale.value = font; skin.value = if (font == 2f) AppSkin.Midnight else AppSkin.Paper }
            val layouts = mutableListOf<TextLayoutResult>()
            compose.onNodeWithText(description, useUnmergedTree = true).performScrollTo().assertIsDisplayed()
                .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
            assertTrue(layouts.isNotEmpty())
            layouts.forEach { layout ->
                assertEquals(font, layout.layoutInput.density.fontScale, 0.001f)
                assertFalse(layout.didOverflowHeight)
                assertEquals(description.length, layout.getLineEnd(layout.lineCount - 1))
                assertFalse((0 until layout.lineCount).any(layout::isLineEllipsized))
            }
            saveConsumerArtPreview("background-gallery-${viewport.value.toInt()}", compose.onRoot().captureToImage().asAndroidBitmap())
            compose.onNodeWithText("茶雾").performScrollTo().performClick()
            compose.runOnIdle { assertEquals("paper_warm", picked); picked = null }
        }
    }
}
