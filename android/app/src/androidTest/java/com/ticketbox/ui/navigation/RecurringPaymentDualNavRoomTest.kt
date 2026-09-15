package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Outer MAIN_ROUTE store vs inner Recurring entry: ordinary Back must not use the payment entry. */
class RecurringPaymentDualNavRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private var sends = 0
    private val harness = FactEntryNavigationHarness(context) { api -> object : ApiService by api {
        override suspend fun debts(lens: String?) = DebtListResponseDto(emptyList(), "CNY")
        override suspend fun createManualExpense(request: ExpenseManualCreateRequestDto): ExpenseDto {
            sends++
            error("Only the worker may send the persisted original")
        }
    } }
    private val mounted = mutableStateOf(true)

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun ordinaryBackOnOuterControllerRestoresDraftFromMainRouteStore() {
        val task = RecurringPaymentTask(
            binding = requireNotNull(harness.screenFactory.repository.captureDeferredLedgerBinding()),
            seriesPublicId = "rec-1",
            period = "2026-08",
            clientRef = "dual-ref",
            merchant = "房租",
            recordedCurrencyCode = "JPY",
            suggestedAmountMinor = 1200,
            ledgerHomeCurrencyCode = "CNY",
        )
        val outerHolder = mutableStateOf<NavHostController?>(null)
        compose.setContent {
            if (!mounted.value) return@setContent
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    val outer = rememberNavController()
                    outerHolder.value = outer
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) { entry ->
                            CompositionLocalProvider(LocalRecurringPaymentDraftHandle provides entry.savedStateHandle) {
                                val inner = rememberNavController()
                                NavHost(inner, startDestination = ProductSecondaryPage.Recurring.route) {
                                    composable(ProductSecondaryPage.Recurring.route) { }
                                }
                            }
                        }
                        addRecurringPaymentRoute(MainNavigationRuntime(outer, harness.shell, harness.screenFactory))
                    }
                }
            }
        }
        compose.waitUntil(10_000) { outerHolder.value != null }
        compose.runOnIdle {
            requireNotNull(outerHolder.value).navigate(recurringPaymentRoute(task))
        }
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.ledger_manual_sheet_title))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNode(hasSetTextAction() and hasText("1200")).performTextReplacement("")
        compose.onNode(hasSetTextAction() and hasText("房租")).performTextReplacement("自填商家")
        closeSoftKeyboard()
        compose.waitForIdle()
        compose.runOnIdle { requireNotNull(outerHolder.value).popBackStack() }
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.ledger_manual_sheet_title))).fetchSemanticsNodes().isEmpty()
        }
        val stored = compose.runOnIdle {
            RecurringPaymentDraftStore(
                requireNotNull(outerHolder.value).getBackStackEntry(MAIN_ROUTE).savedStateHandle,
            ).read("dual-ref")
        }
        assertEquals("", requireNotNull(stored).amountText)
        assertEquals("自填商家", stored.merchant)
        compose.runOnIdle { requireNotNull(outerHolder.value).navigate(recurringPaymentRoute(task)) }
        compose.waitUntil(10_000) {
            compose.onAllNodes(hasText(context.getString(R.string.ledger_manual_sheet_title))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNode(hasSetTextAction() and hasText("1200")).assertDoesNotExist()
        compose.onNodeWithText("自填商家").assertIsDisplayed()
        assertEquals(0, sends)
        assertTrue(harness.fixture.stored().isEmpty())
    }

    @Test fun poppingInnerRecurringReentersTheSamePeriodWithOriginalClientRef() {
        val task = RecurringPaymentTask(
            binding = requireNotNull(harness.screenFactory.repository.captureDeferredLedgerBinding()),
            seriesPublicId = "rec-1",
            period = "2026-08",
            clientRef = "parent-ref",
            merchant = "房租",
            recordedCurrencyCode = "JPY",
            suggestedAmountMinor = 1200,
            ledgerHomeCurrencyCode = "CNY",
        )
        val innerHolder = mutableStateOf<NavHostController?>(null)
        val recovered = mutableStateOf<String?>(null)
        val seedTask = mutableStateOf(true)
        compose.setContent {
            if (!mounted.value) return@setContent
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Default) {
                    val outer = rememberNavController()
                    NavHost(outer, startDestination = MAIN_ROUTE) {
                        composable(MAIN_ROUTE) { entry ->
                            CompositionLocalProvider(LocalRecurringPaymentDraftHandle provides entry.savedStateHandle) {
                                val inner = rememberNavController()
                                innerHolder.value = inner
                                NavHost(inner, startDestination = ProductSecondaryPage.Recurring.route) {
                                    composable(ProductSecondaryPage.Recurring.route) {
                                        val store = rememberRecurringPaymentDraftStore()
                                        LaunchedEffect(Unit) {
                                            if (seedTask.value) {
                                                store.remember(task)
                                                seedTask.value = false
                                            }
                                            recovered.value = store.remembered(
                                                task.binding, task.seriesPublicId, task.period,
                                            )?.clientRef
                                        }
                                    }
                                    composable("other") { recovered.value = null }
                                }
                            }
                        }
                    }
                }
            }
        }
        compose.waitUntil(10_000) { recovered.value == "parent-ref" }
        compose.runOnIdle {
            requireNotNull(innerHolder.value).navigate("other") {
                popUpTo(ProductSecondaryPage.Recurring.route) { inclusive = true }
            }
        }
        compose.waitUntil(10_000) { recovered.value == null }
        compose.runOnIdle { requireNotNull(innerHolder.value).navigate(ProductSecondaryPage.Recurring.route) }
        compose.waitUntil(10_000) { recovered.value == "parent-ref" }
        assertEquals("parent-ref", recovered.value)
        assertEquals(0, sends)
        assertTrue(harness.fixture.stored().isEmpty())
    }
}
