package com.ticketbox.ui.screens.settings

import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.asAndroidBitmap
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.res.stringResource
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsSelected
import androidx.compose.ui.test.captureToImage
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onRoot
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.unit.dp
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class AppearanceThemeChoiceRenderTest {
    @get:Rule
    val composeRule = createComposeRule()

    @Test
    fun themeNamesAndDescriptionsRemainReadableAndSelectableAtLargeFont() {
        val skin = mutableStateOf(AppSkin.Paper)
        val selected = mutableStateOf(AppThemeMode.Paper)
        val labels = mutableMapOf<AppThemeMode, Pair<String, String>>()
        composeRule.setContent {
            val density = LocalDensity.current
            CompositionLocalProvider(LocalDensity provides Density(density.density, 1.8f)) {
                TicketboxTheme(skin = skin.value) {
                    Column(Modifier.width(328.dp).verticalScroll(rememberScrollState())) {
                        AppThemeMode.entries.forEach { mode ->
                            labels[mode] = stringResource(appThemeModeNameRes(mode)) to
                                stringResource(appThemeModeDescriptionRes(mode))
                        }
                        ThemeModePicker(selected.value) { selected.value = it }
                    }
                }
            }
        }
        for (theme in AppSkin.entries) {
            composeRule.runOnIdle { skin.value = theme }
            for (mode in AppThemeMode.entries) {
                val (name, description) = labels.getValue(mode)
                composeRule.onNodeWithText(name).performScrollTo().performClick().assertIsSelected()
                saveConsumerArtPreview("appearance-choice-${theme.name}-${mode.name}-large-font",
                    composeRule.onRoot().captureToImage().asAndroidBitmap())
                for (text in listOf(name, description)) {
                    val layouts = mutableListOf<TextLayoutResult>()
                    composeRule.onNodeWithText(text, useUnmergedTree = true)
                        .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
                    assertTrue("The complete theme choice must be rendered", layouts.isNotEmpty())
                    layouts.forEach { layout ->
                        // String semantics rebuilds a paragraph at the parent's maximum width.
                        // Check the visible lines against the rendered size, as in the budget header check.
                        assertFalse("$theme/$mode: $text must fit its height", layout.didOverflowHeight)
                        assertEquals("The complete theme text must be laid out", text.length,
                            layout.getLineEnd(layout.lineCount - 1))
                        for (line in 0 until layout.lineCount) {
                            assertFalse("Theme descriptions must not be ellipsized", layout.isLineEllipsized(line))
                            assertTrue("$theme/$mode: $text line $line must fit ${layout.size.width}px",
                                layout.getLineLeft(line) >= 0f && layout.getLineRight(line) <= layout.size.width)
                        }
                    }
                }
                composeRule.runOnIdle { assertEquals(mode, selected.value) }
            }
            saveConsumerArtPreview("appearance-choices-${theme.name}-large-font",
                composeRule.onRoot().captureToImage().asAndroidBitmap())
        }
    }
}
