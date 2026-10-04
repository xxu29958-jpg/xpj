package com.ticketbox.ui.appearance.background

import android.os.Build
import android.view.View
import android.view.ViewGroup
import android.view.Window
import android.view.inspector.WindowInspector
import androidx.activity.ComponentActivity
import androidx.activity.enableEdgeToEdge
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.testTag
import androidx.compose.ui.semantics.SemanticsActions
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.junit4.v2.createAndroidComposeRule
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performSemanticsAction
import androidx.compose.ui.text.TextLayoutResult
import androidx.compose.ui.unit.Density
import androidx.compose.ui.window.DialogWindowProvider
import androidx.core.view.WindowInsetsControllerCompat
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.BackgroundSettings
import com.ticketbox.domain.model.ImmersionMode
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.components.AppStatusBanner
import com.ticketbox.ui.design.AppSpacing
import com.ticketbox.ui.screens.settings.BackgroundEditorActions
import com.ticketbox.ui.screens.settings.BackgroundEditorScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.viewmodel.BackgroundEditorState
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class BackgroundEditorViewportTest {
    @get:Rule val compose = createAndroidComposeRule<ComponentActivity>()

    @Test
    fun compositionUsesTheGlobalCanvasEvenUnderTheLocalUnlockBanner() {
        compose.runOnUiThread { compose.activity.enableEdgeToEdge() }
        val skin = mutableStateOf(AppSkin.Paper)
        val scale = mutableStateOf(1f)
        val editor = mutableStateOf(BackgroundEditorState(BackgroundSettings().withBuiltInBackground("paper_warm")))
        var applied = 0
        var cancelled = 0
        compose.setContent {
            TicketboxTheme(skin = skin.value) {
                Box(Modifier.fillMaxSize().testTag("applied-viewport")) {
                    ImmersiveBackgroundScaffold(BackgroundSettings(), skin.value, SurfaceRole.Settings) {
                        // Same existing shell constraints: advisory banner, then weighted body.
                        Column(Modifier.fillMaxSize()) {
                            AppStatusBanner(
                                message = UiText.res(R.string.app_local_unlock_disabled_banner),
                                tone = MessageTone.Info,
                                modifier = Modifier.statusBarsPadding().padding(
                                    horizontal = AppSpacing.screenHorizontal,
                                    vertical = AppSpacing.compactGap,
                                ),
                            )
                            Box(Modifier.weight(1f)) {
                                CompositionLocalProvider(LocalDensity provides Density(LocalDensity.current.density, scale.value)) {
                                    BackgroundEditorScreen(
                                        editor = editor.value,
                                        currentSkin = skin.value,
                                        actions = BackgroundEditorActions(
                                            { editor.value = editor.value.copy(settings = it) },
                                            { cancelled++ }, { applied++; editor.value = editor.value.copy(saving = true) }),
                                    )
                                }
                            }
                        }
                    }
                }
            }
        }

        val appliedViewport = compose.onNodeWithTag("applied-viewport").fetchSemanticsNode().boundsInWindow
        val preview = compose.onNodeWithTag("background-editor-viewport").fetchSemanticsNode().boundsInWindow
        assertEquals("Preview left origin", appliedViewport.left, preview.left, 1f)
        assertEquals("Preview top origin", appliedViewport.top, preview.top, 1f)
        assertEquals("Preview canvas width", appliedViewport.width, preview.width, 1f)
        assertEquals("Preview canvas height", appliedViewport.height, preview.height, 1f)
        assertSystemBarIcons(lightAppearance = true)
        assertSampleAmountFits()
        capture("background-editor-paper")
        compose.runOnIdle { skin.value = AppSkin.Midnight; scale.value = 1.8f }
        assertSystemBarIcons(lightAppearance = false)
        assertSampleAmountFits()
        capture("background-editor-midnight-large")
        compose.onNodeWithText("展开选项").performClick()
        compose.onNodeWithText("统计").performScrollTo().performClick()
        compose.onNodeWithText("统计 · 组件预览").assertIsDisplayed()
        compose.onNodeWithText("专注").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(ImmersionMode.Focus, editor.value.settings.immersionMode) }
        compose.onNodeWithText("应用背景").performScrollTo().performClick()
        compose.onNodeWithText("应用中…").assertIsNotEnabled()
        compose.onNodeWithText("取消").assertIsNotEnabled()
        compose.runOnIdle {
            assertEquals(1, applied); assertEquals(0, cancelled)
            editor.value = editor.value.copy(saving = false,
                message = UiText.res(R.string.appearance_message_background_save_failed))
        }
        compose.onNodeWithText("背景没有保存成功。").performScrollTo().assertIsDisplayed()
        capture("background-editor-retained-draft-large")
        compose.onNodeWithText("取消").performScrollTo().performClick()
        compose.runOnIdle { assertEquals(1, cancelled); assertEquals(ImmersionMode.Focus, editor.value.settings.immersionMode) }
    }

    private fun assertSampleAmountFits() {
        val layouts = mutableListOf<TextLayoutResult>()
        compose.onNodeWithText("¥123,456.78", useUnmergedTree = true).assertIsDisplayed()
            .performSemanticsAction(SemanticsActions.GetTextLayoutResult) { it(layouts) }
        assertTrue(layouts.isNotEmpty())
        layouts.forEach { layout ->
            assertFalse(layout.didOverflowHeight)
            for (line in 0 until layout.lineCount) {
                assertFalse(layout.isLineEllipsized(line))
                assertTrue(layout.getLineRight(line) <= layout.size.width)
            }
        }
    }

    private fun capture(name: String) = saveConsumerArtPreview(name,
        requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))

    private fun assertSystemBarIcons(lightAppearance: Boolean) {
        compose.runOnIdle {
            if (Build.VERSION.SDK_INT >= 29) {
                val window = requireNotNull(WindowInspector.getGlobalWindowViews().firstNotNullOfOrNull(::dialogWindow))
                val bars = WindowInsetsControllerCompat(window, window.decorView)
                assertEquals("Editor status icon appearance", lightAppearance, bars.isAppearanceLightStatusBars)
                assertEquals("Editor navigation icon appearance", lightAppearance, bars.isAppearanceLightNavigationBars)
            }
        }
    }

    private fun dialogWindow(view: View): Window? {
        if (view is DialogWindowProvider) return view.window
        if (view is ViewGroup) {
            for (index in 0 until view.childCount) {
                dialogWindow(view.getChildAt(index))?.let { return it }
            }
        }
        return null
    }
}
