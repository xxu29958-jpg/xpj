package com.ticketbox.ui.navigation

import android.app.Activity
import android.content.Intent
import android.net.Uri
import androidx.activity.compose.LocalActivityResultRegistryOwner
import androidx.activity.result.ActivityResultRegistry
import androidx.activity.result.ActivityResultRegistryOwner
import androidx.activity.result.contract.ActivityResultContract
import androidx.core.app.ActivityOptionsCompat
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.hasContentDescription
import androidx.compose.ui.test.isEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.onNodeWithContentDescription
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.compose.rememberNavController
import androidx.test.espresso.Espresso.closeSoftKeyboard
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.DebtCreateRequestDto
import com.ticketbox.data.remote.dto.DebtBillCaptureDto
import com.ticketbox.data.remote.dto.DebtBillCaptureReceiptDto
import com.ticketbox.data.remote.dto.DebtBillCaptureListDto
import com.ticketbox.data.remote.dto.DebtBillParseOutcomeDto
import com.ticketbox.data.remote.dto.DebtBillParseRequestDto
import com.ticketbox.data.remote.dto.DebtDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.ExpenseAccountingTimeDto
import com.ticketbox.data.repository.CreateDebtDispatcher
import com.ticketbox.data.repository.DebtBillCaptureDispatcher
import com.ticketbox.data.repository.UploadIntentFileStore
import com.ticketbox.data.repository.DebtAdjustmentConnectedNetwork
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.LedgerCalendar
import com.ticketbox.ui.assertEditableTextEquals
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.expense.LocalLedgerCalendarRepository
import com.ticketbox.ui.theme.TicketboxTheme
import java.io.IOException
import java.io.File
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.CompletableDeferred
import okhttp3.MultipartBody
import okhttp3.RequestBody
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import okio.ByteString.Companion.toByteString
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Actual MainNavGraph and disk Room. Only the remote API/session use controlled test data. */
class DebtCreationNavigationRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context get() = InstrumentationRegistry.getInstrumentation().targetContext
    private val skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight") AppSkin.Midnight else AppSkin.Paper
    private val calls = CopyOnWriteArrayList<Pair<DebtCreateRequestDto, String?>>()
    private var acceptedRead = false
    private var listGate: CompletableDeferred<Unit>? = null
    private val response = DebtAdjustmentConnectedNetwork().current.copy(
        publicId = "created-original-debt", ledgerId = "correction-ledger", counterpartyLabel = "原往来 小王",
        direction = "i_owe", principalAmountCents = 12_345_678_901L, remainingAmountCents = 12_345_678_901L,
        paidAmountCents = 0, debtKind = "unspecified", note = null, installmentCount = null, installmentPeriodMonths = null,
        accountingTime = ExpenseAccountingTimeDto("date_only", userLocalDate = "2026-01-31", calendarRevision = 3))
    private var loseReply = true
    private var source: DebtBillCaptureDto? = null
    private var sourceBytes = byteArrayOf()
    private val originalReads = CopyOnWriteArrayList<String>()
    private var pickedFile: File? = null
    private lateinit var navigation: androidx.navigation.NavHostController
    private lateinit var api: ApiService
    private val harness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun runtimeCompatibility() = delegate.runtimeCompatibility().let {
                it.copy(capabilities = it.capabilities.copy(accountingTimeInputVersion = 1, debtBillSourceVersion = 1))
            }
            override suspend fun debts(lens: String?): DebtListResponseDto {
                listGate?.await()
                return DebtListResponseDto(if (acceptedRead) listOf(response) else emptyList(), "CNY")
            }
            override suspend fun debtReceivables() = DebtListResponseDto(emptyList(), "CNY")
            override suspend fun debt(publicId: String) = response
            override suspend fun ledgerCalendar(ledgerId: String, revision: Long?) =
                LedgerCalendar(ledgerId, 3L, "Asia/Shanghai", "adopted", "2026-01-01T00:00:00Z")
            override suspend fun createDebt(request: DebtCreateRequestDto, idempotencyKey: String?): DebtDto {
                calls += request to idempotencyKey
                if (loseReply) throw IOException("Synthetic lost first receipt")
                request.billSource?.let {
                    assertEquals(requireNotNull(source).publicId, it.publicId)
                    assertEquals(requireNotNull(source).rowVersion, it.expectedRowVersion)
                    source = requireNotNull(source).copy(status = "confirmed", adoptedDebtPublicId = response.publicId,
                        rowVersion = it.expectedRowVersion + 1)
                    acceptedRead = true
                }
                return response
            }
            override suspend fun captureDebtBill(file: MultipartBody.Part, creationKey: RequestBody, captureKey: String): DebtBillCaptureReceiptDto {
                sourceBytes = Buffer().also(file.body::writeTo).readByteArray()
                val hash = sourceBytes.toByteString().sha256().hex()
                val originalKey = Buffer().also(creationKey::writeTo).readUtf8()
                source = DebtBillCaptureDto("bill-source", originalKey, captureKey, 1, "pending", hash, hash, "bank.jpg", "verified")
                return DebtBillCaptureReceiptDto("bill-source", originalKey, captureKey, 1, hash, hash)
            }
            override suspend fun debtBillByKey(captureKey: String) = requireNotNull(source).also { assertEquals(captureKey, it.captureKey) }
            override suspend fun parseDebtBillSource(publicId: String, request: DebtBillParseRequestDto, key: String): DebtBillParseOutcomeDto =
                DebtBillParseOutcomeDto(publicId, key, request.expectedRowVersion + 1, "failed", "controlled-provider",
                    errorCode = "debt_bill_provider_unavailable").also {
                    source = requireNotNull(source).copy(rowVersion = it.rowVersion, parseOutcome = it)
                }
            override suspend fun debtBills(creationKey: String?, debtPublicId: String?) = DebtBillCaptureListDto(
                source?.takeIf { it.adoptedDebtPublicId == debtPublicId }?.let(::listOf).orEmpty())
            override suspend fun debtBillOriginal(publicId: String) = sourceBytes.toResponseBody("image/jpeg".toMediaType())
                .also { originalReads += publicId }
        }.also { api = it }
    }.apply { fixture.debtBillSources = true; reopen() }

    @After fun close() { compose.runOnIdle { harness.models.viewModelStore.clear() }; harness.close(); pickedFile?.delete() }

    @Test fun originalBillContinuesThroughCreationAndDetailRead() {
        val initialRead = CompletableDeferred<Unit>().also { listGate = it }
        pickedFile = File(context.cacheDir, "debt-bill-navigation.jpg").apply { writeBytes(harness.fixture.network.originalImage) }
        var pickerLaunched = false
        val registry = object : ActivityResultRegistry() {
            override fun <I, O> onLaunch(requestCode: Int, contract: ActivityResultContract<I, O>, input: I, options: ActivityOptionsCompat?) {
                pickerLaunched = true
                dispatchResult(requestCode, Activity.RESULT_OK, Intent().setData(Uri.fromFile(requireNotNull(pickedFile))))
            }
        }
        mount(object : ActivityResultRegistryOwner { override val activityResultRegistry = registry })
        compose.onNodeWithText(text(R.string.nav_domain_obligations)).performClick()
        compose.waitUntil(5_000) {
            compose.onAllNodes(hasContentDescription(text(R.string.debt_list_parse_bill))).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithContentDescription(text(R.string.debt_list_parse_bill)).assertIsNotEnabled()
        assertTrue(!pickerLaunched)
        initialRead.complete(Unit)
        compose.waitUntil(5_000) {
            compose.onAllNodes(hasContentDescription(text(R.string.debt_list_parse_bill)) and isEnabled()).fetchSemanticsNodes().isNotEmpty()
        }
        compose.onNodeWithContentDescription(text(R.string.debt_list_parse_bill)).performClick()
        try {
            waitFor(text(R.string.debt_bill_capture_waiting))
        } catch (failure: androidx.compose.ui.test.ComposeTimeoutException) {
            val state = compose.runOnIdle {
                (navigation.getBackStackEntry(MAIN_ROUTE).viewModelStore[RelationsDebtComposerViewModelKey]
                    as com.ticketbox.viewmodel.DebtListViewModel).state.value
            }
            throw AssertionError("Picker launched=$pickerLaunched; source inputs=${runBlocking {
                harness.fixture.debtBillInputDao.allInputs().size }}; actual creation state=$state", failure)
        }
        val original = runBlocking { harness.fixture.debtBillInputDao.allInputs().single() }
        assertTrue(calls.isEmpty())
        assertTrue(source == null)
        assertTrue(!original.closed)
        compose.onNodeWithText(text(R.string.debt_create_save)).assertIsNotEnabled()
        runBlocking { assertEquals(1, drain().done) }
        waitFor(text(R.string.debt_bill_suggestion_failed_kept))
        assertTrue(calls.isEmpty())
        field(R.string.debt_create_label_counterparty).performScrollTo().performTextReplacement("原往来 小王")
        field(R.string.debt_create_label_amount).performScrollTo().performTextReplacement("123456789.01")
        field(R.string.debt_principal_date_label).performScrollTo().performTextReplacement("2026-01-31")
        closeSoftKeyboard()
        compose.onNodeWithText(text(R.string.debt_creation_keep_exit)).performClick()
        compose.onNodeWithText(text(R.string.relations_all_debts)).performScrollTo().performClick()
        waitFor(text(R.string.debt_list_add))
        compose.onNodeWithText(text(R.string.debt_list_add)).performClick()
        compose.onNodeWithText(text(R.string.debt_bill_continue_original)).performScrollTo().performClick()
        field(R.string.debt_create_label_counterparty).performScrollTo().assertEditableTextEquals("原往来 小王")
        field(R.string.debt_create_label_amount).performScrollTo().assertEditableTextEquals("123456789.01")
        compose.onNodeWithText(text(R.string.debt_create_save)).assertIsEnabled().performClick()
        waitFor(text(R.string.debt_create_local_saved))
        assertTrue(calls.isEmpty())
        assertEquals("pending", requireNotNull(source).status)
        assertTrue(!runBlocking { requireNotNull(harness.fixture.debtBillInputDao.input(original.captureKey)).closed })
        loseReply = false
        runBlocking { assertEquals(1, drain().done) }
        assertEquals(original.creationKey, calls.single().second)
        assertEquals("bill-source", calls.single().first.billSource?.publicId)
        assertEquals(2L, calls.single().first.billSource?.expectedRowVersion)
        // The source continuation ends only when its accepted backlink is read.
        compose.onNodeWithText(text(R.string.debt_list_add)).performClick()
        compose.onNodeWithText(text(R.string.debt_bill_continue_original)).performScrollTo().performClick()
        compose.waitUntil(5_000) { runBlocking { requireNotNull(harness.fixture.debtBillInputDao.input(original.captureKey)).closed } }
        compose.onNodeWithText(text(R.string.debt_creation_keep_exit)).performClick()
        waitFor("我欠原往来 小王")
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("我欠原往来 小王"))
        compose.onNodeWithText("我欠原往来 小王").performClick()
        // The original is an entry row after the balance and actions; the lazy detail composes it once scrolled to.
        compose.waitUntil(5_000) {
            runCatching { compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("bank.jpg")) }.isSuccess
        }
        capture("debt-bill-detail-entry")
        compose.onNodeWithText("bank.jpg").performClick()
        waitFor(text(R.string.common_confirm))
        assertEquals(listOf("bill-source"), originalReads)
        assertTrue(sourceBytes.isNotEmpty())
        assertEquals(original.payloadJson, runBlocking { requireNotNull(harness.fixture.debtBillInputDao.input(original.captureKey)).payloadJson })
        capture("debt-bill-original-read")
    }

    @Test fun bothRealEntrypointsContinueOneOriginalThenShowTheAcceptedDebt() {
        mount()
        compose.onNodeWithText(text(R.string.nav_domain_obligations)).performClick()
        waitFor(text(R.string.debt_list_add))
        compose.onNodeWithText(text(R.string.debt_list_add)).performClick()
        field(R.string.debt_create_label_counterparty).performTextReplacement("原往来 小王")
        field(R.string.debt_create_label_amount).performScrollTo().performTextReplacement("123456789.01")
        field(R.string.debt_principal_date_label).performScrollTo().performTextReplacement("2026-01-31")
        closeSoftKeyboard()
        compose.onNodeWithText(text(R.string.debt_creation_keep_exit)).performClick()
        compose.onNodeWithText(text(R.string.relations_all_debts)).performScrollTo()
        compose.onNodeWithText(text(R.string.debt_list_add)).assertIsDisplayed()
        compose.onNodeWithText(text(R.string.relations_all_debts)).performClick()
        waitFor(text(R.string.debt_list_add))
        compose.onNodeWithText(text(R.string.debt_list_add)).performClick()
        field(R.string.debt_create_label_counterparty).assertEditableTextEquals("原往来 小王")
        field(R.string.debt_create_label_amount).assertEditableTextEquals("123456789.01")
        field(R.string.debt_principal_date_label).performScrollTo().assertEditableTextEquals("2026-01-31")
        compose.runOnIdle { harness.fixture.role("viewer") }
        waitFor(text(R.string.debt_creation_readonly_original))
        compose.onNodeWithText(text(R.string.debt_create_save)).assertIsNotEnabled()
        compose.onNodeWithText(text(R.string.debt_create_label_counterparty))
            .assertEditableTextEquals("原往来 小王").assertIsNotEnabled()
        capture("debt-original-readonly")
        compose.runOnIdle { harness.fixture.restoreOriginalSession() }
        compose.waitForIdle()
        compose.onNodeWithText(text(R.string.debt_create_label_direction)).performScrollTo()
        capture("debt-original-restored")
        compose.onNodeWithText(text(R.string.debt_create_save)).assertIsEnabled().performClick()
        waitFor(text(R.string.debt_create_local_saved))
        val original = harness.fixture.stored().single()
        assertTrue(calls.isEmpty())
        acceptedRead = true
        runBlocking { assertEquals(1, drain().retryable) }
        loseReply = false
        runBlocking {
            assertEquals(1, drain(harness.fixture.clock.millis() + 120_000).done)
        }
        assertEquals(2, calls.size)
        assertEquals(calls.first(), calls.last())
        assertEquals(original["idempotencyKey"], calls.last().second)
        assertEquals("原往来 小王", calls.last().first.counterpartyLabel)
        assertEquals("i_owe", calls.last().first.direction)
        assertEquals("unspecified", calls.last().first.debtKind)
        assertEquals(12_345_678_901L, calls.last().first.principalAmountCents)
        assertEquals("2026-01-31", calls.last().first.timeInput?.userLocalDate)
        waitFor(context.getString(R.string.debt_list_total_payable, "CNY"))
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("我欠原往来 小王"))
        compose.onNodeWithText("我欠原往来 小王").performClick()
        waitFor(text(R.string.debt_detail_principal))
        compose.onNodeWithText(text(R.string.debt_detail_principal)).assertIsDisplayed()
        compose.onNodeWithText(text(R.string.debt_detail_back)).performClick()
        waitFor("我欠原往来 小王")
        compose.onNodeWithText(text(R.string.debt_list_topbar_back)).performClick()
        waitFor("我欠原往来 小王")
        compose.onNodeWithText(text(R.string.debt_list_add)).assertIsDisplayed()
        capture("relations-root-populated")
        assertEquals(1, harness.fixture.stored().size)
    }

    private fun mount(picker: ActivityResultRegistryOwner? = null) {
        compose.setContent {
            CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models,
                LocalActivityResultRegistryOwner provides (picker ?: requireNotNull(LocalActivityResultRegistryOwner.current)),
                LocalLedgerCalendarRepository provides harness.fixture.ledgerCalendarRepository) {
                TicketboxTheme(skin = skin) {
                    MainNavGraph(MainNavigationRuntime(rememberNavController().also { navigation = it }, harness.shell, harness.screenFactory),
                        remember { SnackbarHostState() },
                        SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                            onThemeModeChange = {}, onCurrencyChange = {}), onBindingCleared = { error("Binding must remain") })
                }
            }
        }
    }
    private fun text(resource: Int) = context.getString(resource)
    private fun capture(name: String) {
        compose.waitForIdle()
        saveConsumerArtPreview(name, requireNotNull(InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot()))
    }
    private fun field(resource: Int) = compose.onNode(hasSetTextAction() and hasText(text(resource)))
    private fun waitFor(value: String) = compose.waitUntil(5_000) { compose.onAllNodesWithText(value).fetchSemanticsNodes().isNotEmpty() }
    private suspend fun drain(now: Long = harness.fixture.clock.millis()) = OutboxDrainEngine(harness.fixture.outbox,
        listOf(CreateDebtDispatcher({ api }, OutboxAdapterGraph().debt.debtCreateAdapter),
            DebtBillCaptureDispatcher({ api }, UploadIntentFileStore(context)::read)), now = { now }).drainOnce()
}
