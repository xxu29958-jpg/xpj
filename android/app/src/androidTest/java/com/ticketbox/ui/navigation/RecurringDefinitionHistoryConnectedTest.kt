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
import java.util.concurrent.CopyOnWriteArrayList
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
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real route, Retrofit and Room; wire history cannot substitute for a reachable user task. */
class RecurringDefinitionHistoryConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val requests = CopyOnWriteArrayList<Request>()
    @Volatile private var failHistoryOnce = false
    private val wire = buildApiService("https://recurring-history.example.test/", OkHttpClient.Builder().addInterceptor { chain ->
        val request = chain.request()
        requests += request
        val history = request.url.encodedPath.endsWith("/history")
        val status = if (history && failHistoryOnce) 503.also { failHistoryOnce = false } else 200
        val body = when {
            status != 200 -> """{"error":"history_unavailable","message":"无法读取计划记录"}"""
            history -> historyJson(request.url.queryParameter("before_version"))
            request.url.encodedPath == "/api/recurring/items" -> """{"items":[${itemJson()}]}"""
            request.url.encodedPath == "/api/insights/recurring-candidates" -> """{"items":[]}"""
            else -> error("Unexpected recurring history request: ${request.url.encodedPath}")
        }
        Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(status).message("Synthetic history transport")
            .body(body.toResponseBody("application/json".toMediaType())).build()
    }.build())
    private val harness = FactEntryNavigationHarness(context) { wire }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun definitionHistoryKeepsOriginalYenAndExplainsTheUnknownHistoryBeforeItsBaseline() {
        mount()
        openHistory()
        waitForText("上一次安排")
        compose.onNodeWithText("更早的记录").performScrollTo().performClick()
        waitForText("旧版固定支出")
        compose.onNodeWithText("旧版固定支出").performScrollTo().assertExists()
        compose.onAllNodesWithText("JPY", substring = true).fetchSemanticsNodes().let { assertTrue(it.isNotEmpty()) }
        compose.onNodeWithText("更早的修改没有记录", substring = true).assertExists()
        assertEquals(listOf(null, "8"), historyRequests().map { it.url.queryParameter("before_version") })
        assertTrue(harness.fixture.stored().isEmpty())
        assertTrue(requests.all { it.method == "GET" })
    }

    @Test fun historyFailureRetryAndBackPreserveDirtyEditorAndThePublishedOriginalIntent() {
        mount()
        compose.onNodeWithTag("recurring-item-history-recurring").performScrollTo().performClick()
        waitForText(context.getString(R.string.recurring_form_title_edit))
        compose.onNode(hasSetTextAction() and hasText("当前固定支出")).performTextReplacement("尚未保存的原名称")
        compose.onNode(hasSetTextAction() and hasText("2400")).performTextReplacement("1250")
        Espresso.closeSoftKeyboard()
        val repository = harness.screenFactory.recurringRepository
        runBlocking {
            val access = requireNotNull(repository.observeActiveLedgerAccess().first())
            val baseline = repository.items().getOrThrow().single()
            repository.updateAllowingOffline(access.binding, baseline,
                RecurringItemPatch(merchant = "已入队的原修改", baselineAmountCents = 1300, homeCurrencyCode = "JPY")).getOrThrow()
        }
        val original = harness.fixture.stored().single()
        failHistoryOnce = true
        openHistory()
        waitForText(context.getString(R.string.common_retry))
        compose.onNodeWithText(context.getString(R.string.common_retry)).performClick()
        waitForText("上一次安排")
        assertEquals(2, historyRequests().size)
        Espresso.pressBack()
        waitForText(context.getString(R.string.recurring_form_title_edit))
        compose.onNode(hasSetTextAction() and hasText("尚未保存的原名称")).assertExists()
        compose.onNode(hasSetTextAction() and hasText("1250")).assertExists()
        assertEquals(original, harness.fixture.stored().single())
        assertTrue(requests.all { it.method == "GET" })
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
        waitForText("当前固定支出")
    }

    private fun openHistory() {
        compose.onNodeWithText("定义历史").performScrollTo().performClick()
        compose.waitUntil(10_000) { historyRequests().isNotEmpty() }
    }

    private fun waitForText(text: String) {
        compose.waitUntil(10_000) { compose.onAllNodesWithText(text, substring = true).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun historyRequests() = requests.filter { it.url.encodedPath == "/api/recurring/items/history-recurring/history" }

    private fun itemJson() = """{"public_id":"history-recurring","ledger_id":"correction-ledger",
        "merchant":"当前固定支出","merchant_key":"original","frequency":"monthly","home_currency_code":"JPY",
        "baseline_amount_cents":2400,"last_amount_cents":1200,"occurrence_count":0,"last_seen_at":null,
        "next_expected_date":"2026-10-09","status":"active","confidence":null,"source":"manual",
        "created_at":"2026-09-01T00:00:00Z","updated_at":"2026-09-20T00:00:00Z",
        "row_version":9,"paused_at":null,"archived_at":null,"next_due_date":"2026-10-09"}"""

    private fun historyJson(before: String?): String {
        val versions = if (before == null) listOf(9, 8) else listOf(7)
        return """{"ledger_id":"correction-ledger","public_id":"history-recurring",
            "items":[${versions.joinToString(",", transform = ::revisionJson)}],"next_before_version":${if (before == null) "8" else "null"}}"""
    }

    private fun revisionJson(version: Int): String {
        val merchant = when (version) { 9 -> "当前固定支出"; 8 -> "上一次安排"; else -> "旧版固定支出" }
        return """{"row_version":$version,"change_kind":"${if (version == 7) "baseline" else "edit"}",
            "recorded_at":"2026-09-${version + 10}T00:00:00Z","actor_account_id":${if (version == 7) "null" else "1"},
            "snapshot":{"merchant":"$merchant","merchant_key":"original","frequency":"monthly",
            "home_currency_code":"JPY","baseline_amount_cents":${(version - 5) * 600},
            "next_expected_date":"2026-10-09","status":"active","source":"manual"}}"""
    }
}
