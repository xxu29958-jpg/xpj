package com.ticketbox.ui

import android.os.Build
import android.os.ParcelFileDescriptor
import android.view.View
import android.view.inspector.WindowInspector
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.ComposeTestRule
import androidx.compose.ui.test.onNodeWithText
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.test.platform.app.InstrumentationRegistry
import org.junit.Assert.assertTrue
import org.junit.rules.ExternalResource

/** Real OS keyboard evidence for existing consumer journeys; restore the emulator setting. */
class RealKeyboard : ExternalResource() {
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private var previousSetting: String? = null

    override fun before() {
        previousSetting = shell("settings get secure show_ime_with_hard_keyboard").trim()
        shell("settings put secure show_ime_with_hard_keyboard 1")
    }

    override fun after() {
        previousSetting?.let { previous ->
            shell(if (previous == "null") "settings delete secure show_ime_with_hard_keyboard"
                else "settings put secure show_ime_with_hard_keyboard $previous")
        }
    }

    fun assertActionAboveKeyboard(compose: ComposeTestRule, label: String, captureName: String) {
        compose.waitUntil(5_000) { compose.runOnIdle { keyboardWindow() != null } }
        // Compose idle alone does not synchronize the separate OS keyboard window.
        compose.waitForIdle()
        instrumentation.uiAutomation.waitForIdle(500, 5_000)
        compose.waitForIdle()
        // Never scroll to the action: it must remain reachable from the current editor.
        val action = compose.onNodeWithText(label).assertIsDisplayed()
        val bounds = action.fetchSemanticsNode().boundsInWindow
        val keyboardTop = compose.runOnIdle {
            val window = requireNotNull(keyboardWindow())
            val insets = requireNotNull(ViewCompat.getRootWindowInsets(window))
            window.height - insets.getInsets(WindowInsetsCompat.Type.ime()).bottom
        }
        saveConsumerArtPreview(captureName, requireNotNull(instrumentation.uiAutomation.takeScreenshot()))
        assertTrue("$label is above the visible OS keyboard", bounds.bottom <= keyboardTop)
        assertTrue("$label remains inside the viewport", bounds.top >= 0f && bounds.height > 0f)
    }

    private fun keyboardWindow(): View? {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            return WindowInspector.getGlobalWindowViews().firstOrNull { window ->
                val insets = ViewCompat.getRootWindowInsets(window)
                window.hasWindowFocus() && insets?.isVisible(WindowInsetsCompat.Type.ime()) == true &&
                    insets.getInsets(WindowInsetsCompat.Type.ime()).bottom > 0
            }
        }
        error("The OS keyboard probe requires API 29 or later; qualification runs on API 36")
    }

    private fun shell(command: String): String = ParcelFileDescriptor.AutoCloseInputStream(
        instrumentation.uiAutomation.executeShellCommand(command),
    ).bufferedReader().use { it.readText() }
}
