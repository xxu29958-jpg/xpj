package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.assertIsOn
import androidx.compose.ui.test.isToggleable
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onAllNodesWithText
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.viewmodel.compose.LocalViewModelStoreOwner
import androidx.navigation.NavHostController
import androidx.navigation.compose.rememberNavController
import androidx.test.core.app.ApplicationProvider
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.repository.MarkNotDuplicateDispatcher
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.toEntity
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import java.io.File

/** Production navigation, original reader, Room admission and dispatcher over controlled remote facts. */
class PendingComparisonNavigationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private lateinit var reference: ExpenseDto
    private lateinit var api: ApiService
    private val mounted = mutableStateOf(true)
    private lateinit var outer: NavHostController
    private val harness: FactEntryNavigationHarness = FactEntryNavigationHarness(context) { delegate ->
        object : ApiService by delegate {
            override suspend fun expense(id: Long) = if (id == reference.id) reference else delegate.expense(id)
            override suspend fun originalHealth(id: Long) = delegate.originalHealth(id).let {
                if (id == reference.id) it.copy(expenseId = id, publicId = requireNotNull(reference.publicId), rowVersion = reference.rowVersion) else it
            }
            override suspend fun expenseThumbnail(id: Long) = delegate.expenseImage(id)
            override suspend fun markNotDuplicate(id: String, request: ExpenseStateTokenRequest, idempotencyKey: String?): ExpenseDto {
                val original = delegate.expense(id.toLong())
                check(request.expectedRowVersion == original.rowVersion && !idempotencyKey.isNullOrBlank())
                return original.copy(duplicateStatus = "none", duplicateOfId = null, rowVersion = original.rowVersion + 1)
                    .also { harness.fixture.network.current = it }
            }
        }.also { api = it }
    }

    @After fun close() {
        compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
        compose.waitForIdle()
        harness.close()
    }

    @Test fun originalsAndDetailReturnToTheComparisonBeforeTheOriginalDecisionIsDelivered() = runBlocking {
        prepare()
        mount()
        waitText(context.getString(R.string.pending_row_action_duplicate))
        compose.onAllNodesWithText(context.getString(R.string.pending_row_action_duplicate))[0].performClick()
        waitText("参考便利店")
        compose.onNodeWithText(context.getString(R.string.pending_duplicate_sheet_keep_both)).assertIsNotEnabled()
        capture("duplicate-native")
        compose.onNode(isToggleable()).performScrollTo().performClick()
        androidx.test.espresso.Espresso.pressBack()
        val resume = context.getString(R.string.pending_review_input_resume,
            context.getString(R.string.pending_row_action_duplicate), "本次便利店")
        waitText(resume)
        capture("duplicate-input-entry")
        compose.onNodeWithText(resume).performScrollTo().performClick()
        waitText("参考便利店")
        compose.onNode(isToggleable()).assertIsOn()
        capture("duplicate-input-resumed")
        compose.onNode(hasText("本次便利店") and hasClickAction()).performScrollTo().performClick()
        waitText(context.getString(R.string.expense_edit_header_title))
        compose.runOnIdle { outer.popBackStack() }
        waitText(context.getString(R.string.pending_duplicate_sheet_title))
        compose.onNode(isToggleable()).assertIsOn()
        compose.onNodeWithText(context.getString(R.string.pending_duplicate_originals)).performScrollTo().performClick()
        compose.waitUntil(10_000) { harness.fixture.network.originalHealthReads.containsAll(listOf(20L, 42L)) }
        compose.waitUntil(10_000) { harness.fixture.network.imageReads.containsAll(listOf(20L, 42L)) }
        capture("duplicate-originals")
        compose.onNodeWithText(context.getString(R.string.pending_duplicate_return)).performClick()
        compose.onNode(isToggleable()).assertIsOn()
        compose.onNodeWithText(context.getString(R.string.pending_duplicate_sheet_keep_both)).performClick()
        compose.waitUntil(10_000) { harness.fixture.stored().size == 1 }
        val row = harness.fixture.stored().single()
        assertEquals("mark_not_duplicate", row["type"])
        assertEquals("7", row["expectedRowVersion"])
        assertEquals("pending", harness.fixture.network.current.status)
        OutboxDrainEngine(harness.fixture.outbox, listOf(MarkNotDuplicateDispatcher(
            { api }, OutboxAdapterGraph().expenseStateTokenAdapter,
            { ledger, expense -> harness.fixture.expenseDao.applyServerExpense(ledger, expense.toEntity(ledger)) },
        )), now = harness.fixture.clock::millis).drainOnce()
        compose.waitUntil(10_000) { compose.onAllNodesWithText(context.getString(R.string.pending_duplicate_sheet_title)).fetchSemanticsNodes().isEmpty() }
        assertEquals("none", harness.fixture.network.current.duplicateStatus)
        assertEquals("pending", harness.fixture.network.current.status)
        assertEquals("confirmed", reference.status)
        assertEquals(2850L, harness.fixture.network.current.originalAmountMinor)
        assertEquals(2850L, reference.originalAmountMinor)
    }

    private fun prepare() {
        InstrumentationRegistry.getArguments().getString("captureImage")?.let {
            harness.fixture.network.originalImageOverride = File(it).readBytes()
        }
        harness.fixture.network.current = harness.fixture.network.current.copy(status = "pending", confirmedAt = null,
            merchant = "本次便利店", duplicateStatus = "suspected", duplicateOfId = 20L,
            originalCurrencyCode = "JPY", originalAmountMinor = 2850, originalCurrency = "JPY", originalAmount = "2850",
            imagePath = "controlled/current.png")
        reference = harness.fixture.network.current.copy(id = 20L, publicId = "comparison-reference", merchant = "参考便利店",
            status = "confirmed", duplicateStatus = "none", duplicateOfId = null, confirmedAt = "2026-09-06T00:00:00Z")
    }

    private fun waitText(text: String) = compose.waitUntil(10_000) { compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty() }

    private fun capture(name: String) {
        compose.waitForIdle()
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.waitForIdle(250, 5_000)
        saveConsumerArtPreview(name, requireNotNull(automation.takeScreenshot()))
    }

    private fun mount() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight") AppSkin.Midnight else AppSkin.Paper) {
                    val controller = rememberNavController()
                    outer = controller
                    MainNavGraph(MainNavigationRuntime(controller, harness.shell, harness.screenFactory), remember { SnackbarHostState() },
                        SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                            onThemeModeChange = {}, onCurrencyChange = {}), onBindingCleared = { error("Keep the original binding") })
                }
            }
        }
    }
}
