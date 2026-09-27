package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onAllNodesWithContentDescription
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.buildApiService
import com.ticketbox.data.remote.dto.DebtActivityListDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.repository.DebtTask
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.components.displayDateTime
import com.ticketbox.ui.theme.TicketboxTheme
import java.net.ConnectException
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real routes and Retrofit reads, followed by new query owners over the same disk Room. */
class DebtOfflineReadingConnectedTest {
    @JvmField @Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val requests = CopyOnWriteArrayList<Request>()
    @Volatile private var offline = false
    private val wire = buildApiService("https://debt-reading.example.test/", OkHttpClient.Builder()
        .addInterceptor { chain ->
            val request = chain.request()
            requests += request
            if (offline) throw ConnectException("Debt transport unavailable")
            val body = when (request.url.encodedPath) {
                "/api/debts" -> """{"items":[$DEBT],"home_currency_code":"JPY"}"""
                "/api/debts/$DEBT_ID" -> DEBT
                "/api/debts/$DEBT_ID/activity" -> activityJson(
                    requireNotNull(request.url.queryParameter("page")).toInt())
                else -> error("Unexpected Debt read: ${request.url}")
            }
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200)
                .message("Isolated Debt wire").body(body.toResponseBody("application/json".toMediaType())).build()
        }.build())
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun debts(lens: String?): DebtListResponseDto = wire.debts(lens)
            override suspend fun debt(publicId: String): DebtDto = wire.debt(publicId)
            override suspend fun debtActivity(publicId: String, page: Int,
                focusRepayment: String?): DebtActivityListDto = wire.debtActivity(publicId, page, focusRepayment)
        }
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun previouslyReadDebtAndActivitySurviveOfflineRoomReopenWithoutInventingUnreadPages() {
        val originalIntent = runBlocking { harness.saveFailedCorrection() }
        val originalBinding = harness.fixture.graph.expenseRepository.captureDeferredLedgerBinding()
        installMainGraph()
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.AllDebts) }
        openDebt()
        assertActivity("已记录日元还款", PAYMENT_TIME)
        olderPage()
        assertActivity("首次记录日元往来", CREATION_TIME)
        val onlineDebt = runBlocking { harness.fixture.graph.debtRepository.getDebt(DEBT_ID).getOrThrow() }
        assertEquals("JPY", onlineDebt.value.homeCurrencyCode)
        assertEquals(1_200L, onlineDebt.value.originalAmountMinor)
        assertEquals(900L, onlineDebt.value.remainingAmountCents)
        assertEquals(300L, onlineDebt.value.paidAmountCents)
        assertEquals(4L, onlineDebt.value.rowVersion)
        assertTrue(!onlineDebt.fromCache)
        val task = DebtTask(requireNotNull(originalBinding), DEBT_ID)
        val onlinePaymentPage = runBlocking {
            harness.fixture.graph.debtRepository.activity.listActivity(task, 1, null).getOrThrow()
        }
        val payment = requireNotNull(onlinePaymentPage.value.items.single().repayment)
        assertEquals(300L, payment.amountCents)
        assertEquals("JPY", payment.originalCurrencyCode)
        assertEquals(300L, payment.originalAmountMinor)
        assertEquals(PAYMENT_TIME, onlinePaymentPage.value.items.single().recordedAt)
        assertTrue(requests.any { it.url.encodedPath.endsWith("/activity") && it.url.queryParameter("page") == "2" })
        assertTrue(requests.none { it.url.queryParameter("page") == "3" })

        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        offline = true
        compose.runOnIdle { harness.reopen(); mounted.value = true }
        compose.waitForIdle()
        // This must fail on the old guarded-GET-only owner, rather than on a new test API.
        openDebt()
        assertActivity("已记录日元还款", PAYMENT_TIME)
        olderPage()
        assertActivity("首次记录日元往来", CREATION_TIME)
        val reopenedDebt = runBlocking { harness.fixture.graph.debtRepository.getDebt(DEBT_ID).getOrThrow() }
        assertEquals(onlineDebt.value, reopenedDebt.value)
        assertEquals(onlineDebt.fetchedAt, reopenedDebt.fetchedAt)
        assertTrue(reopenedDebt.fromCache)
        val offlinePaymentPage = runBlocking {
            harness.fixture.graph.debtRepository.activity.listActivity(task, 1, null).getOrThrow()
        }
        assertEquals(onlinePaymentPage.value, offlinePaymentPage.value)
        assertEquals(onlinePaymentPage.fetchedAt, offlinePaymentPage.fetchedAt)
        assertTrue(offlinePaymentPage.fromCache)
        val unread = runBlocking { harness.fixture.graph.debtRepository.activity.listActivity(task, 3, null) }
        assertTrue("A never-read page must remain unavailable offline", unread.isFailure)
        assertActivity("首次记录日元往来", CREATION_TIME)
        assertEquals(originalBinding, harness.fixture.graph.expenseRepository.captureDeferredLedgerBinding())
        assertEquals(listOf(originalIntent), harness.fixture.stored())
        assertTrue("Offline reading must not send any fact command", requests.all { it.method == "GET" })
    }

    private fun installMainGraph() {
        compose.setContent {
            if (mounted.value) {
                CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                    TicketboxTheme(skin = AppSkin.Paper) {
                        MainNavGraph(MainNavigationRuntime(rememberNavController(), harness.shell, harness.screenFactory),
                            remember { SnackbarHostState() },
                            SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                                onThemeModeChange = { error("Must preserve appearance") },
                                onCurrencyChange = { error("Must preserve display currency") }),
                            onBindingCleared = { error("Must preserve the session") })
                    }
                }
            }
        }
        compose.waitForIdle()
    }

    private fun openDebt() {
        waitForText("原日元往来")
        val source = context.getString(if (offline) R.string.debt_read_cached_title else R.string.debt_read_title)
        compose.onNodeWithText(source, substring = true).assertIsDisplayed()
        compose.onNodeWithText("原日元往来").performClick()
        compose.waitUntil(5_000) {
            compose.onAllNodesWithContentDescription(context.getString(R.string.debt_detail_back)).fetchSemanticsNodes().isNotEmpty()
        }
        waitForText(source, substring = true)
        // Cached-source feedback can put the note outside the lazy viewport; reach it by scrolling.
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("原债务备注"))
        compose.onNodeWithText("原债务备注").performScrollTo().assertIsDisplayed()
    }

    private fun olderPage() {
        val label = context.getString(R.string.debt_repayment_history_older)
        compose.onNodeWithText(label).performScrollTo().performClick()
    }

    private fun assertActivity(reason: String, recordedAt: String) {
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(R.string.debt_activity_title)))
        waitForText(reason)
        compose.onNodeWithText(reason).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("${displayDateTime(recordedAt)} · 原记录人").assertIsDisplayed()
    }

    private fun waitForText(value: String, substring: Boolean = false) {
        compose.waitUntil(5_000) { compose.onAllNodesWithText(value, substring = substring).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun activityJson(page: Int): String {
        check(page in 1..2) { "The online journey must not prefetch the unread third page" }
        val event = if (page == 1) """{"kind":"repayment","public_id":"debt-payment",
            "recorded_at":"$PAYMENT_TIME","actor_display_name":"原记录人","actor_is_you":false,
            "amount_cents":300,"reason":"已记录日元还款","repayment":{"public_id":"debt-payment",
            "amount_cents":300,"paid_at":"2026-08-09","created_at":"$PAYMENT_TIME","status":"active",
            "original_currency_code":"JPY","original_amount_minor":300}}""" else
            """{"kind":"created","public_id":"debt-created","recorded_at":"$CREATION_TIME",
            "actor_display_name":"原记录人","actor_is_you":false,"amount_cents":1200,"reason":"首次记录日元往来"}"""
        return """{"debt_public_id":"$DEBT_ID","home_currency_code":"JPY","items":[$event],
            "page":$page,"page_size":1,"total":3}"""
    }

    private companion object {
        const val DEBT_ID = "offline-jpy-debt"
        const val PAYMENT_TIME = "2026-08-09T03:04:05Z"
        const val CREATION_TIME = "2026-07-01T06:07:08Z"
        const val DEBT = """{"public_id":"offline-jpy-debt","ledger_id":"correction-ledger",
            "direction":"i_owe","counterparty_type":"external","counterparty_label":"原日元往来",
            "principal_amount_cents":1200,"remaining_amount_cents":900,"paid_amount_cents":300,
            "status":"open","source_type":"manual","home_currency_code":"JPY",
            "original_currency_code":"JPY","original_amount_minor":1200,"note":"原债务备注",
            "created_at":"2026-07-01T06:07:08Z","updated_at":"2026-08-09T03:04:05Z","row_version":4}"""
    }
}
