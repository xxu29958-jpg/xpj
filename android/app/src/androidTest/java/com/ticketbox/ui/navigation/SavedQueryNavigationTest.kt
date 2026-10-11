package com.ticketbox.ui.navigation

import android.content.Context
import androidx.compose.material3.SnackbarHostState
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasClickAction
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasSetTextAction
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
import androidx.test.espresso.Espresso
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.data.remote.ApiService
import com.ticketbox.R
import com.ticketbox.data.remote.dto.ConfirmedExpenseStreamItemDto
import com.ticketbox.data.remote.dto.ConfirmedStreamEntryKindDto
import com.ticketbox.data.remote.dto.ExpenseLineageStatusDto
import com.ticketbox.data.remote.dto.SavedViewDto
import com.ticketbox.data.remote.dto.SavedViewListDto
import com.ticketbox.data.remote.dto.SavedViewResultsDto
import com.ticketbox.data.remote.dto.SavedViewResultRowDto
import com.ticketbox.data.remote.dto.SavedViewUpdateRequestDto
import com.ticketbox.data.remote.dto.TagListItemDto
import com.ticketbox.data.remote.dto.TagManagementListDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.AppThemeMode
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.theme.TicketboxTheme
import java.io.IOException
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Production Graph, Room, navigation, ViewModel and screens; controlled remote/session fixture. */
class SavedQueryNavigationTest {
    @get:Rule val compose = createComposeRule()
    private val context = ApplicationProvider.getApplicationContext<Context>()
    private var query = SavedViewDto("household-query", "每月日用", 4, "current", null, "", "daily", "日用", "CNY", null, "便利店", "购物")
    private val receipts = mutableMapOf<String, SavedViewDto>()
    private val keys = mutableListOf<String>()
    private var readFailure = false
    private lateinit var harness: FactEntryNavigationHarness
    private val mounted = mutableStateOf(true)

    @Test fun queryResultReturnAndUnknownEditKeepOriginalTaskAcrossRoomReopen() {
        harness = FactEntryNavigationHarness(context) { api -> queryApi(api) }
        harness.fixture.network.current = harness.fixture.network.current.copy(merchant = "便利店", category = "购物", amountCents = 12860,
            originalCurrencyCode = "JPY", originalAmountMinor = 2850, homeCurrency = "CNY")
        install()
        enterDirectory()
        click("每月日用")
        waitFor("¥128.60")
        capture("saved-query-results")
        click("便利店")
        waitFor(context.getString(R.string.expense_fact_original_spend))
        harness.fixture.network.current = harness.fixture.network.current.copy(merchant = "便利店后来更正")
        Espresso.pressBack()
        waitFor("便利店后来更正")
        capture("saved-query-after-detail")
        click("修改条件或名称")
        waitFor("下次一键找到")
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextReplacement("每月家庭日用")
        capture("saved-query-editor")
        compose.onNode(hasText("保存这组查询") and hasClickAction()).performClick()
        waitFor("核实原提交")
        capture("saved-query-unknown")
        val originalKey = keys.single()
        query = query.copy(name = "后来人工条件", rowVersion = 12, queryText = "后来条件")
        val originalBinding = requireNotNull(harness.fixture.graph.savedQueryRepository.captureBinding())
        compose.runOnIdle { mounted.value = false }
        compose.waitForIdle()
        harness.reopen()
        val retained = runBlocking { harness.fixture.graph.savedQueryRepository.readDrafts(originalBinding).getOrThrow().single() }
        assertEquals(originalKey, retained.key)
        assertEquals(4L, retained.baseline?.rowVersion)
        assertEquals("每月家庭日用", retained.definition.name)
        compose.runOnIdle { mounted.value = true }
        compose.waitForIdle()
        enterDirectory()
        click("每月家庭日用")
        waitFor("核实原提交")
        harness.fixture.role("viewer")
        waitFor("当前为只读，可查看查询；原输入保留。")
        compose.onNode(hasText("核实原提交") and hasClickAction()).assertIsNotEnabled()
        harness.fixture.role("member")
        compose.waitUntil { compose.onNode(hasText("核实原提交") and hasClickAction()).fetchSemanticsNode().config.contains(androidx.compose.ui.semantics.SemanticsProperties.Disabled).not() }
        compose.onNode(hasText("核实原提交") and hasClickAction()).performClick()
        waitFor("已取得原提交的首次结果。")
        assertEquals(listOf(originalKey, originalKey), keys)
        assertEquals(1, receipts.size)
        assertEquals("后来人工条件", query.name)
        compose.onNode(hasText("完成并读取当前查询") and hasClickAction()).performClick()
        waitFor("后来人工条件")
        click("后来人工条件")
        waitFor("便利店后来更正")
        capture("saved-query-current-result")
        Espresso.pressBack()
        readFailure = true
        click("后来人工条件")
        waitFor("重新读取")
        assertTrue(compose.onAllNodesWithText("没有符合这些条件的流水").fetchSemanticsNodes().isEmpty())
        capture("saved-query-read-failure")
        readFailure = false
        click("重新读取")
        waitFor("便利店后来更正")
    }

    private fun queryApi(base: ApiService) = object : ApiService by base {
        override suspend fun savedViews() = SavedViewListDto(listOf(query))
        override suspend fun savedView(publicId: String) = query
        override suspend fun listManagedTags() = TagManagementListDto(listOf(TagListItemDto("daily", "日用", 1, 1)))
        override suspend fun savedViewResults(publicId: String, page: Int): SavedViewResultsDto {
            if (readFailure) throw IOException("controlled read unavailable")
            val root = harness.fixture.network.current
            val entry = ConfirmedExpenseStreamItemDto(ConfirmedStreamEntryKindDto.Expense, "2026-10-03", "2026-10-03T12:00:00Z",
                root.id, 12860, root, lineageStatus = ExpenseLineageStatusDto.Confirmed, lineageHomeNetCents = 12860)
            return SavedViewResultsDto(mapOf("ledger_id" to "correction-ledger", "month" to "2026-10", "q" to query.queryText,
                "category" to query.category, "tag" to "日用", "home_currency_code" to query.homeCurrencyCode),
                listOf(SavedViewResultRowDto(entry, 12860, null)), page, 50, 1)
        }
        override suspend fun updateSavedView(publicId: String, request: SavedViewUpdateRequestDto, idempotencyKey: String): SavedViewDto {
            keys += idempotencyKey
            val replay = receipts[idempotencyKey]
            if (replay != null) return replay
            assertEquals(query.rowVersion, request.expectedRowVersion)
            query = query.copy(name = request.name, queryText = request.queryText, rowVersion = query.rowVersion + 1)
            receipts[idempotencyKey] = query
            throw IOException("accepted reply lost")
        }
    }

    private fun install() {
        compose.setContent {
            if (mounted.value) CompositionLocalProvider(LocalViewModelStoreOwner provides harness.models) {
                TicketboxTheme(skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight") AppSkin.Midnight else AppSkin.Paper) {
                    MainNavGraph(MainNavigationRuntime(rememberNavController(), harness.shell, harness.screenFactory),
                        remember { SnackbarHostState() }, SettingsPreferenceControls(AppSkin.Paper, AppThemeMode.System, CurrencyCode.CNY,
                            onThemeModeChange = {}, onCurrencyChange = {}), onBindingCleared = { error("Preserve binding") })
                }
            }
        }
    }

    private fun enterDirectory() {
        compose.runOnIdle { harness.shell.openSecondaryPage(ProductSecondaryPage.GlobalSearch) }
        waitFor(context.getString(R.string.global_search_header_title))
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("常用查询") and hasClickAction())
        click("常用查询")
        waitFor(query.name)
    }

    private fun click(text: String) = compose.onNode(hasText(text) and hasClickAction()).performScrollTo().performClick()
    private fun waitFor(text: String) = compose.waitUntil(5_000) { compose.onAllNodesWithText(text).fetchSemanticsNodes().isNotEmpty() }
    private fun capture(name: String) {
        compose.waitForIdle()
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.waitForIdle(300, 3_000)
        saveConsumerArtPreview(name, requireNotNull(automation.takeScreenshot()))
    }

    @After fun close() {
        if (::harness.isInitialized) {
            compose.runOnIdle { mounted.value = false; harness.models.viewModelStore.clear() }
            compose.waitForIdle()
            harness.close()
        }
    }
}
