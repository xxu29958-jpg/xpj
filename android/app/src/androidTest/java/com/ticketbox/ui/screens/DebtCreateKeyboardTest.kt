package com.ticketbox.ui.screens

import android.os.ParcelFileDescriptor
import android.view.View
import android.view.inspector.WindowInspector
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import androidx.core.view.ViewCompat
import androidx.core.view.WindowInsetsCompat
import androidx.lifecycle.viewModelScope
import androidx.test.filters.SdkSuppress
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtListViewModel
import kotlinx.coroutines.cancel
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Before
import org.junit.Rule
import org.junit.Test

/** Real modal sheet and OS IME; only the already-covered durable publication boundary is gated. */
@SdkSuppress(minSdkVersion = 29)
class DebtCreateKeyboardTest {
    @get:Rule val compose = createComposeRule()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val skin = mutableStateOf(AppSkin.Paper)
    private lateinit var viewModel: DebtListViewModel
    private var priorKeyboardSetting: String? = null

    @Before
    fun showSoftwareKeyboardOnTheCloudEmulator() {
        priorKeyboardSetting = shell("settings get secure show_ime_with_hard_keyboard").trim()
        shell("settings put secure show_ime_with_hard_keyboard 1")
    }

    @After
    fun restoreKeyboardAndStopViewModel() {
        if (::viewModel.isInitialized) compose.runOnIdle { viewModel.viewModelScope.cancel() }
        priorKeyboardSetting?.let { previous ->
            if (previous == "null") {
                shell("settings delete secure show_ime_with_hard_keyboard")
            } else {
                shell("settings put secure show_ime_with_hard_keyboard $previous")
            }
        }
    }

    @Test
    fun saveStaysWithinTouchReachWhileEditingWithTheRealKeyboard() {
        val creation = SheetCreationGate()
        compose.setContent {
            viewModel = remember { DebtListViewModel(sheetQueries(), creation) }
            TicketboxTheme(skin = skin.value) {
                DebtListScreen(
                    viewModel,
                    DebtListScreenActions(onBack = {}, onOpenDebt = {}, onParseBillImage = {}, onOpenSyncStatus = {}),
                )
            }
        }
        compose.waitUntil(5_000) { ::viewModel.isInitialized && viewModel.state.value.homeCurrencyResolved }
        compose.onNodeWithText(text(R.string.debt_list_add)).performTouchInput { click() }
        val counterparty = compose.onAllNodes(hasSetTextAction())[0]
        counterparty.performScrollTo().performTouchInput { click() }
        counterparty.performTextInput("小王")
        assertSaveAboveKeyboard("debt-create-keyboard-paper")

        val amount = compose.onAllNodes(hasSetTextAction())[1]
        amount.performScrollTo().performTouchInput { click() }
        amount.performTextInput("123.45")
        assertSaveAboveKeyboard("debt-create-keyboard-amount")
        val note = compose.onAllNodes(hasSetTextAction())[2]
        note.performScrollTo().performTouchInput { click() }
        note.performTextInput("出差垫付车费，等本月报销到账后归还")
        compose.runOnIdle { skin.value = AppSkin.Midnight }
        assertSaveAboveKeyboard("debt-create-keyboard-midnight")

        compose.onNodeWithText(text(R.string.debt_create_save)).performTouchInput { click() }
        compose.waitUntil(5_000) { viewModel.state.value.isSubmitting }
        compose.runOnIdle {
            assertEquals(1, creation.submitted.size)
            assertEquals(12_345L, creation.submitted.single().principalAmountCents)
            assertEquals("小王", creation.submitted.single().counterpartyLabel)
            assertEquals("出差垫付车费，等本月报销到账后归还", creation.submitted.single().note)
        }
        creation.accept.complete(Unit)
        compose.waitUntil(5_000) { viewModel.state.value.pendingCreations.isNotEmpty() && !viewModel.state.value.isSubmitting }
        compose.onNodeWithText(text(R.string.debt_create_pending_body)).assertIsDisplayed()
        compose.runOnIdle { assertTrue(viewModel.state.value.debts.isEmpty()) }
    }

    private fun assertSaveAboveKeyboard(captureName: String) {
        compose.waitUntil(5_000) { compose.runOnIdle { keyboardWindow() != null } }
        saveConsumerArtPreview(captureName, requireNotNull(instrumentation.uiAutomation.takeScreenshot()))
        val save = compose.onNodeWithText(text(R.string.debt_create_save))
        // No scroll-to-Save here: the action must stay reachable from the current editor.
        save.assertIsDisplayed()
        val bounds = save.fetchSemanticsNode().boundsInWindow
        val keyboardTop = compose.runOnIdle {
            val window = requireNotNull(keyboardWindow())
            val insets = requireNotNull(ViewCompat.getRootWindowInsets(window))
            window.height - insets.getInsets(WindowInsetsCompat.Type.ime()).bottom
        }
        assertTrue("Save is above the visible OS keyboard", bounds.bottom <= keyboardTop)
        assertTrue("Save remains inside the sheet viewport", bounds.top >= 0f && bounds.height > 0f)
    }

    private fun keyboardWindow(): View? = WindowInspector.getGlobalWindowViews().firstOrNull { window ->
        val insets = ViewCompat.getRootWindowInsets(window)
        window.hasWindowFocus() && insets?.isVisible(WindowInsetsCompat.Type.ime()) == true &&
            insets.getInsets(WindowInsetsCompat.Type.ime()).bottom > 0
    }

    private fun text(resource: Int): String = instrumentation.targetContext.getString(resource)

    private fun shell(command: String): String = ParcelFileDescriptor.AutoCloseInputStream(
        instrumentation.uiAutomation.executeShellCommand(command),
    ).bufferedReader().use { it.readText() }
}
