package com.ticketbox.ui.screens

import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.click
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTouchInput
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.RealKeyboard
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtListViewModel
import kotlinx.coroutines.cancel
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real modal sheet and OS IME; only the already-covered durable publication boundary is gated. */
class DebtCreateKeyboardTest {
    @get:Rule val compose = createComposeRule()
    @get:Rule val keyboard = RealKeyboard()
    private val instrumentation = InstrumentationRegistry.getInstrumentation()
    private val skin = mutableStateOf(AppSkin.Paper)
    private lateinit var viewModel: DebtListViewModel
    @After
    fun stopViewModel() {
        if (::viewModel.isInitialized) compose.runOnIdle { viewModel.viewModelScope.cancel() }
    }

    @Test
    fun saveStaysWithinTouchReachWhileEditingWithTheRealKeyboard() {
        val creation = SheetCreationGate()
        compose.setContent {
            viewModel = remember { DebtListViewModel(sheetQueries(), creation, initialAdjustmentReadFixture(creation.currentAccess())) }
            TicketboxTheme(skin = skin.value) {
                DebtListScreen(
                    viewModel,
                    DebtListScreenActions(onBack = {}, onOpenDebt = {}, onParseBillImage = {}, onOpenSyncStatus = {}),
                )
            }
        }
        compose.waitUntil(5_000) { ::viewModel.isInitialized && viewModel.state.value.homeCurrencyResolved }
        compose.onNodeWithText(text(R.string.debt_list_add)).performTouchInput { click() }
        compose.waitForIdle()
        instrumentation.uiAutomation.waitForIdle(500, 5_000)
        saveConsumerArtPreview("debt-create-header", requireNotNull(instrumentation.uiAutomation.takeScreenshot()))
        val counterparty = compose.onNode(hasSetTextAction() and hasText(text(R.string.debt_create_label_counterparty)))
        counterparty.performScrollTo().performTouchInput { click() }
        counterparty.performTextInput("小王")
        assertSaveAboveKeyboard("debt-create-keyboard-paper")
        compose.onNodeWithText(text(R.string.debt_create_save)).performTouchInput { click() }
        compose.onNodeWithText(text(R.string.debt_create_validation_error)).assertIsDisplayed()
        compose.runOnIdle {
            assertTrue(creation.submitted.isEmpty())
            assertEquals("小王", viewModel.state.value.addDraft.counterpartyLabel)
        }
        assertSaveAboveKeyboard("debt-create-keyboard-validation")

        val amount = compose.onNode(hasSetTextAction() and hasText(text(R.string.debt_create_label_amount)))
        amount.performScrollTo().performTouchInput { click() }
        amount.performTextInput("123.45")
        assertSaveAboveKeyboard("debt-create-keyboard-amount")
        val note = compose.onNode(hasSetTextAction() and hasText(text(R.string.debt_create_label_note)))
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
        keyboard.assertActionAboveKeyboard(compose, text(R.string.debt_create_save), captureName)
    }

    private fun text(resource: Int): String = instrumentation.targetContext.getString(resource)
}
