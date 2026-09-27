package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithTag
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.espresso.Espresso
import com.ticketbox.R
import com.ticketbox.data.remote.buildApiService
import com.ticketbox.data.repository.RecurringItemPatch
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.theme.TicketboxTheme
import java.net.ConnectException
import java.util.concurrent.CopyOnWriteArrayList
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.async
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real route, Retrofit and reopened disk Room; no synthetic query cache or future API symbols. */
class RecurringOfflineReadingConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val requests = CopyOnWriteArrayList<Request>()
    private val lateStarted = CountDownLatch(2)
    private val releaseLate = CountDownLatch(1)
    @Volatile private var offline = false
    @Volatile private var holdReads = false
    private val wire = buildApiService("https://recurring-offline.example.test/", OkHttpClient.Builder().addInterceptor { chain ->
        val request = chain.request()
        requests += request
        if (offline) throw ConnectException("Synthetic unavailable recurring transport")
        if (holdReads && (request.url.encodedPath == "/api/recurring/items" || request.url.encodedPath.endsWith("/history"))) {
            lateStarted.countDown()
            check(releaseLate.await(10, TimeUnit.SECONDS)) { "Late recurring response was not released" }
        }
        val rejected = request.url.encodedPath == "/api/goals/refused-goal"
        val body = if (rejected) """{"error":"forbidden","message":"账本访问已被拒绝"}""" else responseJson(request)
        Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(if (rejected) 403 else 200)
            .message("Synthetic recurring transport").body(body.toResponseBody("application/json".toMediaType())).build()
    }.build())
    private val harness = FactEntryNavigationHarness(context) { wire }

    @After fun close() {
        releaseLate.countDown()
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun coldOfflineListStillOpensReadOriginalCurrencyOccurrenceAndHistoryButNeverInventsUnreadPages() {
        mount()
        val repository = harness.screenFactory.recurringRepository
        val binding = runBlocking { requireNotNull(repository.observeActiveLedgerAccess().first()).binding }
        val originalPeriod = runBlocking { repository.occurrences.fetch(binding, "offline-active", "2026-09").getOrThrow() }
        val originalHistory = runBlocking { repository.history(binding, "offline-active", null).getOrThrow() }
        openHistory()
        waitForText("原日元安排")
        Espresso.pressBack()
        showArchived()
        openHistory()
        waitForText("原美元归档安排")
        Espresso.pressBack()
        selectTab(R.string.recurring_tab_active)
        offline = true
        restart()
        // This is the first missing business postcondition on the frozen production source.
        waitForText("原日元固定支出")
        compose.onNodeWithTag("recurring-item-offline-active").assertExists()
        openHistory()
        waitForText("原日元安排")
        compose.onNodeWithText("更早的记录").performScrollTo().performClick()
        waitForText(context.getString(R.string.common_retry))
        compose.onNodeWithText("从未读取的安排").assertDoesNotExist()
        compose.onNodeWithText("原日元安排").assertExists()
        Espresso.pressBack()
        val reopened = harness.screenFactory.recurringRepository
        runBlocking {
            assertEquals(originalHistory, reopened.history(binding, "offline-active", null).getOrThrow())
            assertEquals(originalPeriod, reopened.occurrences.fetch(binding, "offline-active", "2026-09").getOrThrow())
            assertTrue(reopened.occurrences.fetch(binding, "offline-active", "2026-08").isFailure)
            val rows = reopened.items(binding, includeArchived = true).getOrThrow()
            assertEquals(mapOf("offline-active" to "JPY", "offline-archived" to "USD"), rows.associate { it.publicId to it.homeCurrencyCode })
            assertEquals(2400L, rows.single { it.publicId == "offline-active" }.baselineAmountCents)
        }
        showArchived()
        openHistory()
        waitForText("原美元归档安排")
        assertTrue(harness.fixture.stored().isEmpty())
        assertTrue(requests.all { it.method == "GET" })
    }

    @Test fun sharedRefusalBlocksLateReadPublicationAndRestartWithoutReplacingDirtyEditorOrOriginalOutbox() {
        mount()
        val repository = harness.screenFactory.recurringRepository
        val binding = runBlocking { requireNotNull(repository.observeActiveLedgerAccess().first()).binding }
        runBlocking { repository.occurrences.fetch(binding, "offline-active", "2026-09").getOrThrow() }
        compose.onNodeWithTag("recurring-item-offline-active").performScrollTo().performClick()
        waitForText(context.getString(R.string.recurring_form_title_edit))
        compose.onNode(hasSetTextAction() and hasText("原日元固定支出")).performTextReplacement("未确认的原名称")
        compose.onNode(hasSetTextAction() and hasText("2400")).performTextReplacement("1250")
        Espresso.closeSoftKeyboard()
        runBlocking {
            val baseline = repository.items(binding, includeArchived = true).getOrThrow().single { it.publicId == "offline-active" }
            repository.updateAllowingOffline(binding, baseline, RecurringItemPatch(merchant = "已入队的原修改",
                baselineAmountCents = 1300, homeCurrencyCode = "JPY")).getOrThrow()
        }
        val original = harness.fixture.stored().single()
        openHistory()
        waitForText("原日元安排")
        holdReads = true
        val outcomes = runBlocking {
            val list = async(Dispatchers.IO) { repository.items(binding, includeArchived = true) }
            val history = async(Dispatchers.IO) { repository.history(binding, "offline-active", 9) }
            try {
                assertTrue("Both original reads must be in flight before refusal", lateStarted.await(10, TimeUnit.SECONDS))
                assertTrue(harness.fixture.graph.reportsRepository.goal("refused-goal", binding).isFailure)
            } finally { releaseLate.countDown() }
            list.await().isFailure to history.await().isFailure
        }
        waitForText(context.getString(R.string.recurring_form_title_edit))
        compose.onNodeWithText("原日元安排").assertDoesNotExist()
        compose.onNode(hasSetTextAction() and hasText("未确认的原名称")).assertExists()
        compose.onNode(hasSetTextAction() and hasText("1250")).assertExists()
        assertEquals(original, harness.fixture.stored().single())
        assertTrue("A list begun before shared refusal must not become readable or publish a durable snapshot", outcomes.first)
        assertTrue("A history begun before shared refusal must not become readable", outcomes.second)
        offline = true
        restart()
        val reopened = harness.screenFactory.recurringRepository
        runBlocking {
            assertTrue(reopened.items(binding, includeArchived = true).isFailure)
            assertTrue(reopened.history(binding, "offline-active", null).isFailure)
            assertTrue(reopened.occurrences.fetch(binding, "offline-active", "2026-09").isFailure)
        }
        compose.onNodeWithTag("recurring-item-offline-active").assertDoesNotExist()
        assertEquals(original, harness.fixture.stored().single())
        assertFalse(requests.any { it.method != "GET" })
    }

    private fun mount() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = AppSkin.Paper) {
                    NavHost(rememberNavController(), startDestination = ProductSecondaryPage.Recurring.route) {
                        composable(ProductSecondaryPage.Recurring.route) { RecurringRoute(harness.screenFactory, {}) }
                    }
                }
            }
        }
        waitForText("原日元固定支出")
    }

    private fun restart() {
        val previousRequests = requests.size
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.reopen()
        compose.runOnIdle { mounted.value = true }
        compose.waitUntil(10_000) { requests.drop(previousRequests).any { it.url.encodedPath == "/api/insights/recurring-candidates" } }
        compose.waitForIdle()
    }

    private fun openHistory() {
        compose.onNodeWithText("定义历史").performScrollTo().performClick()
    }

    private fun showArchived() {
        selectTab(R.string.recurring_tab_archived)
        waitForText("原美元归档固定支出")
    }

    private fun selectTab(label: Int) {
        val title = context.getString(R.string.recurring_tab_label_count, context.getString(label), 1)
        compose.onNodeWithText(title).performScrollTo().performClick()
    }

    private fun waitForText(text: String) {
        compose.waitUntil(10_000) { compose.onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun responseJson(request: Request): String = when {
        request.url.encodedPath.endsWith("/history") -> historyJson(request.url.pathSegments[3], request.url.queryParameter("before_version"))
        "/occurrences/" in request.url.encodedPath -> occurrenceJson()
        request.url.encodedPath == "/api/recurring/items" -> """{"items":[${itemJson(false)},${itemJson(true)}]}"""
        request.url.encodedPath == "/api/insights/recurring-candidates" -> """{"items":[]}"""
        else -> error("Unexpected recurring request: ${request.url.encodedPath}")
    }

    private fun itemJson(archived: Boolean): String = """{"public_id":"offline-${if (archived) "archived" else "active"}",
        "ledger_id":"correction-ledger","merchant":"${if (archived) "原美元归档固定支出" else "原日元固定支出"}",
        "merchant_key":"original","frequency":"monthly","home_currency_code":"${if (archived) "USD" else "JPY"}",
        "baseline_amount_cents":2400,"last_amount_cents":1200,"occurrence_count":0,"last_seen_at":null,
        "next_expected_date":"2026-10-09","status":"${if (archived) "archived" else "active"}","confidence":null,"source":"manual",
        "created_at":"2026-09-01T00:00:00Z","updated_at":"2026-09-20T00:00:00Z",
        "row_version":9,"paused_at":null,"archived_at":${if (archived) "\"2026-09-20T00:00:00Z\"" else "null"},
        "next_due_date":${if (archived) "null" else "\"2026-10-09\""}}"""

    private fun historyJson(id: String, before: String?): String = """{"ledger_id":"correction-ledger","public_id":"$id",
        "items":[{"row_version":${if (before == null) 9 else 8},"change_kind":"edit","recorded_at":"2026-09-19T12:30:00Z",
        "actor_account_id":1,"snapshot":${definitionJson(if (before != null) "从未读取的安排"
            else if (id == "offline-archived") "原美元归档安排" else "原日元安排", id == "offline-archived")}}],
        "next_before_version":${if (before == null) 9 else "null"}}"""

    private fun definitionJson(merchant: String, archived: Boolean = false): String = """{"merchant":"$merchant",
        "merchant_key":"original","frequency":"monthly","home_currency_code":"${if (archived) "USD" else "JPY"}",
        "baseline_amount_cents":1200,"next_expected_date":"2026-09-09","status":"${if (archived) "archived" else "active"}","source":"manual"}"""

    private fun occurrenceJson(): String = """{"series_public_id":"offline-active","period":"2026-09",
        "series_row_version":9,"row_version":3,"state":"unfulfilled","planned_amount_cents":2400,
        "reserved_amount_cents":2400,"expense_public_id":null,"paid_amount_cents":null,
        "next_due_date":"2026-10-09","home_currency_code":"JPY",
        "recorded_definition":{"series_row_version":7,"recorded_at":"2026-09-12T12:30:00Z",
        "snapshot":${definitionJson("首次记录依据")}}}"""
}
