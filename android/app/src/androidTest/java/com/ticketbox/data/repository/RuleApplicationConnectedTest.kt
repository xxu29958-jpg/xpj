package com.ticketbox.data.repository

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.settings.CategoryRuleDefinitionActions
import com.ticketbox.ui.screens.settings.CategoryRulesApplicationActions
import com.ticketbox.ui.screens.settings.CategoryRulesApplicationState
import com.ticketbox.ui.screens.settings.CategoryRulesInteractionState
import com.ticketbox.ui.screens.settings.CategoryRulesRuleActions
import com.ticketbox.ui.screens.settings.CategoryRulesRuleListState
import com.ticketbox.ui.screens.settings.CategoryRulesScreen
import com.ticketbox.ui.screens.settings.CategoryRulesScreenActions
import com.ticketbox.ui.screens.settings.CategoryRulesScreenState
import com.ticketbox.ui.screens.settings.CategoryRulesStatusState
import com.ticketbox.ui.screens.settings.CategoryRulesUndoActions
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.CategoryRulesViewModel
import java.io.IOException
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Rule
import org.junit.Test

/** Production Graph, disk Room, ViewModel and Compose; the remote service is controlled. */
class RuleApplicationConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val network = RuleApplicationConnectedNetwork()
    private val fixture = DebtAdjustmentConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext, network.api)
    private var model by mutableStateOf<CategoryRulesViewModel?>(null)

    @After fun close() {
        compose.runOnIdle { model?.viewModelScope?.cancel() }
        fixture.close()
    }

    @Test fun applyReopensOriginalThenKeepsReceiptThroughReadFailureAndRoomReopen() {
        reopen()
        showScreen()
        compose.waitUntil(10_000) { model!!.uiState.value.binding != null }
        compose.onNodeWithText("预览", substring = false).performScrollTo().performClick()
        compose.waitUntil(10_000) { model!!.uiState.value.confirmedRulesPreview != null }
        compose.onNodeWithText("确认应用", substring = false).performScrollTo().performClick()
        compose.waitUntil(10_000) { model!!.uiState.value.pendingApplications.isNotEmpty() }
        val original = fixture.stored().single()
        assertEquals(emptyList<String>(), network.keys)
        reopen()
        assertEquals(original, fixture.stored().single())
        assertEquals(1, drain().failures)
        compose.waitUntil(10_000) { model!!.uiState.value.pendingApplications.singleOrNull()?.canRetry == true }
        compose.onNodeWithText("原预览扫描 9 笔已确认账单，预计改写 1 笔。").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("预览", substring = false).assertDoesNotExist()
        capture("rule-application-original")
        network.currentCategory = "医疗"
        network.loseReply = false
        compose.onNodeWithText("核实原应用").performScrollTo().performClick()
        compose.waitUntil(10_000) { model!!.uiState.value.pendingApplications.singleOrNull()?.row?.status == com.ticketbox.data.local.PendingMutationStatus.Pending }
        assertEquals(1, drain().done)
        compose.waitUntil(10_000) { model!!.uiState.value.pendingApplications.singleOrNull()?.needsRefresh == true }
        val accepted = fixture.stored().single()
        reopen()
        assertEquals(accepted, fixture.stored().single())
        compose.waitUntil(10_000) { model!!.uiState.value.pendingApplications.singleOrNull()?.needsRefresh == true }
        compose.onNodeWithText("首次结果：改写 1 笔。这是原应用结果，不代表当前分类。").performScrollTo().assertIsDisplayed()
        capture("rule-application-accepted-refresh")
        network.failRead = false
        compose.onNodeWithText("刷新流水").performScrollTo().performClick()
        compose.waitUntil(10_000) { model!!.uiState.value.pendingApplications.singleOrNull()?.needsRefresh == false }
        assertEquals(listOf(original["idempotencyKey"], original["idempotencyKey"]), network.keys)
        assertEquals(original["payload"], fixture.stored().single()["payload"])
        assertEquals("医疗", network.currentCategory)
        assertEquals(2, network.reads)
        assertEquals(1, network.receipts.size)
        runBlocking { assertEquals(emptyList<OutboxRow>(), fixture.outbox.observeStatus().first().refreshRequired) }
    }

    private fun reopen() {
        compose.runOnIdle { model?.viewModelScope?.cancel() }
        val graph = fixture.reopen()
        compose.runOnIdle { model = CategoryRulesViewModel(graph.ruleRepository, graph.expenseRepository) }
    }

    private fun drain() = runBlocking {
        val adapters = OutboxAdapterGraph()
        OutboxDrainEngine(fixture.outbox, listOf(ApplyConfirmedRulesDispatcher({ network.api }, adapters.ruleApplicationAdapter,
            adapters.ruleApplicationReceiptAdapter) { fixture.graph.ruleRepository.refreshAcceptedApplication(it).getOrThrow() }),
            maxAttempts = 1, now = fixture.clock::millis).drainOnce()
    }

    private fun capture(name: String) {
        compose.waitForIdle()
        val automation = InstrumentationRegistry.getInstrumentation().uiAutomation
        automation.waitForIdle(250, 5_000)
        saveConsumerArtPreview(name, requireNotNull(automation.takeScreenshot()))
    }

    private fun showScreen() = compose.setContent {
        val active = requireNotNull(model)
        val state by active.uiState.collectAsStateWithLifecycle()
        val definitions by active.definitions.state.collectAsStateWithLifecycle()
        TicketboxTheme(skin = AppSkin.Default) {
            CategoryRulesScreen(CategoryRulesScreenState(
                CategoryRulesRuleListState(state.categoryRules, state.categoryRulesLoading, state.categoryRulesLoadFailed),
                CategoryRulesInteractionState(state.busy, !state.canModify), CategoryRulesStatusState(state.message, state.messageTone),
                CategoryRulesApplicationState(state.ruleApplications, state.ruleApplicationsLoading, state.confirmedRulesPreview, state.ruleApplicationsLoadFailed),
                state.undoableRule, applicationSubmissions = state.pendingApplications, selectedSubmissionId = state.selectedSubmissionId,
                binding = state.binding, definitions = definitions),
                CategoryRulesScreenActions({}, CategoryRulesRuleActions(active::toggleCategoryRule, active::deleteCategoryRule,
                    active::recoverSubmission, { active.loadCategoryRules() }),
                    CategoryRulesApplicationActions(active::previewApplyConfirmedRules, active::confirmApplyConfirmedRules,
                        active::rollbackRuleApplication, { active.loadRuleApplications() }, active::recoverApplication),
                    CategoryRulesUndoActions(active::undoDelete, active::dismissUndo),
                    CategoryRuleDefinitionActions(active.definitions::begin, active.definitions::open, active.definitions::change,
                        active.definitions::submit, active.definitions::close, active.definitions::reviewBinding, active.definitions::reload)))
        }
    }
}

private class RuleApplicationConnectedNetwork {
    val keys = mutableListOf<String>()
    val receipts = mutableMapOf<String, RuleApplyConfirmedResponseDto>()
    var loseReply = true
    var failRead = true
    var reads = 0
    var currentCategory = "其他"
    val api = object : ApiService by DebtAdjustmentConnectedNetwork().service {
        override suspend fun categoryRules(): List<CategoryRuleDto> = emptyList()
        override suspend fun ruleApplications(limit: Int) = RuleApplicationListDto(emptyList())
        override suspend fun confirmedExpenses(query: Map<String, String>): PaginatedExpensesDto {
            reads += 1
            if (failRead) throw IOException("Synthetic read failure after acceptance")
            return PaginatedExpensesDto(items = emptyList(), total = 0, page = 1, pageSize = 50)
        }
        override suspend fun applyConfirmedRules(request: RuleApplyConfirmedRequestDto, limit: Int, maxScan: Int,
            idempotencyKey: String?): RuleApplyConfirmedResponseDto {
            if (!request.confirm) return RuleApplyConfirmedResponseDto(true, 9, 1, previewToken = "original-preview", scanLimit = 500)
            check(request.previewToken == "original-preview")
            val key = requireNotNull(idempotencyKey)
            keys += key
            val receipt = receipts.getOrPut(key) {
                currentCategory = "餐饮"
                RuleApplyConfirmedResponseDto(false, 9, 1, commandKey = key, applicationPublicId = "accepted-batch", scanLimit = 500)
            }
            if (loseReply) throw IOException("Synthetic lost application reply")
            return receipt
        }
    }
}
