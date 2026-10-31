package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.repository.ManualEntryTemplateStore
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.assertEditableTextEquals
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.After
import org.junit.Assert.*
import org.junit.Rule
import org.junit.Test

/** Real template UI -> existing manual form/ViewModel -> one durable original; no implicit save. */
class WidgetTemplateEntryRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private var sends = 0
    private val harness = FactEntryNavigationHarness(context) { api -> object : ApiService by api {
        override suspend fun debts(lens: String?) = DebtListResponseDto(emptyList(), "CNY")
        override suspend fun createManualExpense(request: ExpenseManualCreateRequestDto): ExpenseDto {
            sends++
            error("The existing worker owns delivery")
        }
    } }
    private val mounted = mutableStateOf(true)
    private val store = ManualEntryTemplateStore(context, requireNotNull(harness.screenFactory.repository.captureDeferredLedgerBinding()))
    private var createdId: String? = null

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        createdId?.let(store::remove)
        harness.close()
    }

    @Test fun createEditAndUseTemplateRequireAnExplicitBillConfirmation() {
        val originalIds = store.read().map { it.id }.toSet()
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    if (mounted.value) {
                        val nav = rememberNavController()
                        NavHost(nav, startDestination = "template-ledger") {
                            composable("template-ledger") { LedgerRoute(nav, harness.shell, harness.screenFactory) }
                        }
                    }
                }
            }
        }
        compose.runOnIdle { dispatchShortcutNavigation(ShortcutTarget.EntryTemplates, harness.shell) }
        awaitText(R.string.widget_template_add)
        compose.onNodeWithText(context.getString(R.string.widget_template_add)).performScrollTo().performClick()
        compose.waitUntil(10_000) { compose.onAllNodes(hasSetTextAction()).fetchSemanticsNodes().size >= 4 }
        listOf("工作日早餐", "12.50", "餐饮", "豆浆").forEachIndexed { index, value ->
            compose.onAllNodes(hasSetTextAction())[index].performScrollTo().performTextInput(value)
        }
        closeSoftKeyboard()
        saveTemplate()
        compose.waitUntil(10_000) { store.read().any { it.id !in originalIds } }
        val template = store.read().single { it.id !in originalIds }
        createdId = template.id
        assertEquals(1250L, template.amountMinor)
        assertTrue(harness.fixture.stored().isEmpty())
        compose.onNodeWithText(context.getString(R.string.widget_template_edit)).performScrollTo().performClick()
        compose.waitUntil(10_000) { compose.onAllNodes(hasSetTextAction()).fetchSemanticsNodes().size >= 4 }
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextReplacement("18.00")
        closeSoftKeyboard()
        saveTemplate()
        compose.waitUntil(10_000) { store.read().single { it.id == template.id }.amountMinor == 1800L }
        compose.onNodeWithText(context.getString(R.string.widget_template_use)).performScrollTo().performClick()
        awaitText(R.string.ledger_manual_save_button)
        val amount = compose.onAllNodes(hasSetTextAction())[0]
        amount.assertEditableTextEquals("18.00")
        assertTrue(harness.fixture.stored().isEmpty())
        assertEquals(0, sends)
        amount.performScrollTo().performTextReplacement("19.25")
        closeSoftKeyboard()
        compose.onNodeWithText(context.getString(R.string.ledger_manual_save_button)).performClick()
        compose.waitUntil(10_000) { harness.fixture.stored().size == 1 }
        val request = requireNotNull(OutboxAdapterGraph().manualCreateAdapter.fromJson(requireNotNull(harness.fixture.stored().single()["payload"])))
        assertEquals("19.25", request.originalAmount)
        assertEquals("餐饮", request.category)
        assertEquals("豆浆", request.note)
        assertEquals(1800L, store.read().single { it.id == template.id }.amountMinor)
        assertEquals(0, sends)
    }

    private fun saveTemplate() = compose.onNodeWithText(context.getString(R.string.widget_template_save)).performScrollTo().performClick()
    private fun awaitText(resource: Int) = compose.waitUntil(10_000) {
        compose.onAllNodes(hasText(context.getString(resource))).fetchSemanticsNodes().isNotEmpty()
    }
}
