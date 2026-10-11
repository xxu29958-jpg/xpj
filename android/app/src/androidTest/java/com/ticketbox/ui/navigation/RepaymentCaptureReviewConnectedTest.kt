package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.buildApiService
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.RepaymentDraftConfirmRequestDto
import com.ticketbox.data.remote.dto.RepaymentDraftDto
import com.ticketbox.data.remote.dto.RepaymentDraftListResponseDto
import com.ticketbox.data.repository.ConfirmRepaymentDraftDispatcher
import com.ticketbox.data.repository.LedgerRequestGuard
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import java.io.IOException
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.runBlocking
import okhttp3.OkHttpClient
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import org.json.JSONObject
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Production route, Room, Retrofit and Outbox; only identity and the remote transport are controlled. */
class RepaymentCaptureReviewConnectedTest {
    @JvmField @Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private val mounted = mutableStateOf(true)
    private val sent = CopyOnWriteArrayList<Pair<String?, String>>()
    @Volatile private var loseReply = true
    @Volatile private var confirmed = false
    @Volatile private var calendarRevision = 3
    private val wire = buildApiService("https://capture-review.example.test/", OkHttpClient.Builder()
        .addInterceptor { chain ->
            val request = chain.request()
            val body = when (request.url.encodedPath) {
                "/api/debts" -> """{"items":[$DEBT],"home_currency_code":"CNY"}"""
                    .replace("\"revision\":3", "\"revision\":$calendarRevision")
                "/api/repayment-drafts" -> """{"items":[${currentCapture()}]}"""
                "/api/repayment-drafts/capture" -> currentCapture()
                "/api/repayment-drafts/capture/confirm" -> {
                    val bytes = Buffer().also { requireNotNull(request.body).writeTo(it) }.readUtf8()
                    sent += request.header("Idempotency-Key") to bytes
                    if (loseReply) throw IOException("Original reply was lost")
                    confirmed = true
                    currentCapture()
                }
                else -> error("Unexpected capture request: ${request.url}")
            }
            Response.Builder().request(request).protocol(Protocol.HTTP_1_1).code(200).message("Controlled capture transport")
                .body(body.toResponseBody("application/json".toMediaType())).build()
        }.build())
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun debts(lens: String?): DebtListResponseDto = wire.debts(lens)
            override suspend fun repaymentDrafts(status: String?): RepaymentDraftListResponseDto = wire.repaymentDrafts(status)
            override suspend fun repaymentDraft(publicId: String): RepaymentDraftDto = wire.repaymentDraft(publicId)
            override suspend fun confirmRepaymentDraft(publicId: String, request: RepaymentDraftConfirmRequestDto,
                idempotencyKey: String?): RepaymentDraftDto = wire.confirmRepaymentDraft(publicId, request, idempotencyKey)
        }
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun reviewedDateAndAmountReturnThroughTheOriginalRouteAndLostReply() {
        installGraph()
        openReview()
        val amount = InstrumentationRegistry.getArguments().getString("captureAmount") ?: "90.00"
        assertEquals(2, compose.onAllNodes(hasSetTextAction()).fetchSemanticsNodes().size)
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextReplacement(amount)
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextReplacement("2026-08-31")
        compose.onNodeWithText(context.getString(R.string.debt_proposal_back_keep_draft)).performClick()
        waitForText(R.string.repayment_review_open)
        calendarRevision = 9
        reopenGraph()
        openReview()
        compose.onNodeWithText("2026-08-31").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(amount).assertExists()
        capture("capture-review-edit")
        compose.onNodeWithText(context.getString(R.string.repayment_review_confirm)).assertIsDisplayed().performClick()
        compose.waitUntil(5_000) { runBlocking { harness.fixture.stored().size == 1 } }
        val original = runBlocking { harness.fixture.stored().single() }
        drain()
        assertEquals("pending", runBlocking { harness.fixture.stored().single()["status"] })
        reopenGraph()
        openReview()
        compose.onNodeWithText("2026-08-31").performScrollTo().assertIsDisplayed()
        assertTrue(compose.onAllNodes(hasSetTextAction()).fetchSemanticsNodes().isEmpty())
        capture("capture-review-original")
        showStatus(R.string.repayment_review_waiting)
        loseReply = false
        // A lost reply remains queued for the worker, so it must not become a new manual write.
        compose.onNodeWithText(context.getString(R.string.repayment_review_retry)).assertDoesNotExist()
        drain()
        showStatus(R.string.repayment_review_done)
        capture("capture-review-receipt")
        val completed = runBlocking { harness.fixture.stored().single() }
        assertEquals("done", completed["status"])
        assertEquals(original["payload"], completed["payload"])
        assertEquals(original["idempotencyKey"], completed["idempotencyKey"])
        assertEquals(2, sent.size)
        assertEquals(sent[0], sent[1])
        val payload = JSONObject(sent[0].second)
        assertEquals(amount, payload.getString("original_amount"))
        assertEquals(7, payload.getInt("expected_row_version"))
        val date = payload.getJSONObject("time_input")
        assertEquals("2026-08-31", date.getString("user_local_date"))
        assertEquals(3, date.getInt("calendar_revision"))
        assertEquals("date_only", date.getString("precision"))
        assertTrue(!date.has("instant") && !date.has("instant_utc"))
        androidx.test.espresso.Espresso.pressBack()
        val history = context.getString(R.string.repayment_draft_history_count, 1)
        compose.waitUntil(5_000) { compose.onAllNodesWithText(history).fetchSemanticsNodes().isNotEmpty() }
        compose.onNodeWithText(history).performScrollTo().performClick()
        waitForText(R.string.repayment_review_history)
        compose.waitForIdle()
        capture("capture-history-list")
        compose.onNodeWithText(context.getString(R.string.repayment_review_history)).performScrollTo()
        capture("capture-history-record")
        compose.onNodeWithText(context.getString(R.string.repayment_review_history)).performClick()
        showStatus(R.string.repayment_review_done)
        compose.onNodeWithText("2026-08-31").performScrollTo().assertIsDisplayed()
        assertTrue(compose.onAllNodes(hasSetTextAction()).fetchSemanticsNodes().isEmpty())
    }

    private fun openReview() {
        compose.runOnIdle { harness.shell.openRepaymentDrafts() }
        waitForText(R.string.repayment_review_open)
        compose.waitForIdle()
        capture("capture-inbox")
        compose.onNodeWithText(context.getString(R.string.repayment_review_open)).performScrollTo()
        capture("capture-inbox-record")
        compose.onNodeWithText(context.getString(R.string.repayment_review_open)).performClick()
        waitForText(R.string.repayment_review_title)
    }

    private fun reopenGraph() {
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        compose.runOnIdle { harness.reopen(); mounted.value = true }
        compose.waitForIdle()
    }

    private fun drain() = runBlocking {
        val adapters = OutboxAdapterGraph()
        OutboxDrainEngine(harness.fixture.outbox, listOf(ConfirmRepaymentDraftDispatcher(
            LedgerRequestGuard(harness.fixture.apiProvider), adapters.repaymentReviewAdapter, adapters.repaymentDraftReceiptAdapter)),
            now = harness.fixture.clock::millis).drainOnce()
    }

    private fun waitForText(id: Int) {
        compose.waitUntil(5_000) { compose.onAllNodesWithText(context.getString(id)).fetchSemanticsNodes().isNotEmpty() }
    }

    private fun showStatus(id: Int) {
        // Status is a later lazy item; large text requires real scrolling before it can be read.
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(context.getString(id)))
        compose.onNodeWithText(context.getString(id)).assertIsDisplayed()
    }

    private fun capture(name: String) = saveConsumerArtPreview(name,
        requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))

    private fun currentCapture(): String = if (!confirmed) CAPTURE else
        CAPTURE.replace("\"pending\"", "\"confirmed\"").dropLast(1) +
            """, "committed_debt_public_id":"original-debt", "committed_repayment_public_id":"original-payment"}"""

    private fun installGraph() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
                    AppSkin.Midnight else AppSkin.Paper) {
                    MainNavGraph(MainNavigationRuntime(rememberNavController(), harness.shell, harness.screenFactory),
                        remember { SnackbarHostState() }, SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                            onThemeModeChange = { error("Preserve appearance") }, onCurrencyChange = { error("Preserve currency") }),
                        onBindingCleared = { error("Preserve identity") })
                }
            }
        }
    }

    private companion object {
        const val CAPTURE = """{"public_id":"capture","source":"alipay","amount_cents":30000,"home_currency_code":"CNY",
            "original_currency_code":"CNY","original_amount_minor":30000,"merchant_label":"原还款通知",
            "captured_at":"2026-09-02T00:00:00Z","status":"pending","suggested_debt_public_id":"original-debt",
            "created_at":"2026-09-02T00:00:01Z"}"""
        const val DEBT = """{"public_id":"original-debt","ledger_id":"correction-ledger","direction":"i_owe",
            "counterparty_type":"external","counterparty_label":"一起旅行垫付费用的朋友",
            "principal_amount_cents":20000000000,"remaining_amount_cents":20000000000,"paid_amount_cents":0,
            "status":"open","source_type":"manual","home_currency_code":"CNY","original_currency_code":"CNY",
            "original_amount_minor":20000000000,"created_at":"2026-07-01T00:00:00Z","updated_at":"2026-09-02T00:00:00Z",
            "row_version":7,"repayment_calendar":{"revision":3,"timezone_name":"Pacific/Honolulu"}}"""
    }
}
