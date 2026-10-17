package com.ticketbox.data.repository

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.click
import androidx.compose.ui.test.performTouchInput
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.PaginatedExpensesDto
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.data.remote.dto.RuleApplicationBatchDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackRequestDto
import com.ticketbox.data.remote.dto.RuleApplicationRollbackPreviewDto
import com.ticketbox.data.remote.dto.RuleRollbackSkippedItemDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedRequestDto
import com.ticketbox.data.remote.dto.RuleApplyConfirmedResponseDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.RealKeyboard
import com.ticketbox.ui.screens.settings.CategoryRuleDefinitionActions
import com.ticketbox.ui.screens.settings.CategoryRulesApplicationActions
import com.ticketbox.ui.screens.settings.CategoryRulesApplicationState
import com.ticketbox.ui.screens.settings.CategoryRuleRollbackActions
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
    @get:Rule val keyboard = RealKeyboard()
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
        compose.onNodeWithText("预览已确认账单", substring = false).performScrollTo().performClick()
        compose.waitUntil(10_000) { model!!.uiState.value.confirmedRulesPreview != null }
        compose.onNodeWithText("例如：按商家统一分类").performScrollTo().performTouchInput { click() }
            .performTextInput("按商家统一分类")
        keyboard.assertActionAboveKeyboard(compose, "确认应用", "rule-application-reason-ime")
        compose.onNodeWithText("按商家统一分类", substring = false).assertIsDisplayed()
        keyboard.dismissAndWait(compose)
        capture("rule-application-reason")
        compose.onNodeWithText("确认应用", substring = false).assertIsDisplayed().performClick()
        compose.waitUntil(10_000) { model!!.uiState.value.pendingApplications.isNotEmpty() }
        val original = fixture.stored().single()
        assertEquals(emptyList<String>(), network.keys)
        reopen()
        assertEquals(original, fixture.stored().single())
        network.applicationResponse = RuleApplyConfirmedResponseDto(false, 9, 1, commandKey = original["idempotencyKey"],
            applicationPublicId = "accepted-batch", scanLimit = 500)
        assertEquals(1, drain().failures)
        compose.waitUntil(10_000) { model!!.uiState.value.pendingApplications.singleOrNull()?.canRetry == true }
        compose.onNodeWithText("原预览扫描 9 笔已确认账单，预计改写 1 笔。").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("预览已确认账单", substring = false).assertDoesNotExist()
        capture("rule-application-original")
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
        assertEquals(2, network.reads)
        assertEquals(listOf("按商家统一分类", "按商家统一分类"), network.applicationRequests.map { it.reason })
        assertEquals(listOf("original-preview", "original-preview"), network.applicationRequests.map { it.previewToken })
        runBlocking { assertEquals(emptyList<OutboxRow>(), fixture.outbox.observeStatus().first().refreshRequired) }
    }

    @Test fun rollbackPreviewAndOriginalReasonSurviveReadFailureAndLostReply() {
        network.showBatch = true
        reopen()
        showScreen()
        compose.waitUntil(10_000) { model!!.uiState.value.ruleApplications.size == 1 }
        compose.onNodeWithText("规则应用记录").performScrollTo().performClick()
        compose.onNodeWithText("回退", substring = false).performScrollTo().performClick()
        compose.waitUntil(10_000) { model!!.uiState.value.rollback.error != null }
        compose.onNodeWithText("核对范围后回退").assertIsDisplayed().assertIsNotEnabled()
        compose.onNodeWithText("例如：核对后撤回本批次").performScrollTo().performTouchInput { click() }
            .performTextInput("核对后撤回本批次")
        keyboard.assertActionAboveKeyboard(compose, "核对范围后回退", "rule-rollback-reason-ime")
        compose.onNodeWithText("核对后撤回本批次", substring = false).assertIsDisplayed()
        keyboard.dismissAndWait(compose)
        network.previewFails = false
        compose.onNodeWithText("重新预览").performScrollTo().performClick()
        compose.waitUntil(10_000) { model!!.uiState.value.rollback.preview != null }
        compose.onNodeWithText("当前可回退 1 笔 · 保留 1 笔").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("查看 1 笔保留项").performScrollTo().performClick()
        compose.onNodeWithText("应用后已有修改，保留当前事实").performScrollTo().assertIsDisplayed()
        capture("rule-rollback-eligibility")
        network.rollbackAccepted = true
        compose.onNodeWithText("回退允许的 1 笔").assertIsDisplayed().performClick()
        compose.waitUntil(10_000) { model!!.uiState.value.rollback.error != null }
        assertEquals("核对后撤回本批次", model!!.uiState.value.rollback.submittedReason)
        capture("rule-rollback-lost-reply")
        network.rollbackLosesReply = false
        compose.onNodeWithText("核实原回退").assertIsDisplayed().performClick()
        compose.waitUntil(10_000) { model!!.uiState.value.ruleApplications.single().isRolledBack }
        compose.onNodeWithText("已恢复 1 笔 · 跳过 1 笔").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("回退说明：核对后撤回本批次").performScrollTo().assertIsDisplayed()
        capture("rule-rollback-reason-history")
        assertEquals(listOf("accepted-batch" to "核对后撤回本批次", "accepted-batch" to "核对后撤回本批次"), network.rollbackRequests)
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
        compose.waitForIdle()
        saveConsumerArtPreview(name, requireNotNull(automation.takeScreenshot()))
    }

    private fun showScreen() = compose.setContent {
        val active = requireNotNull(model)
        val state by active.uiState.collectAsStateWithLifecycle()
        val definitions by active.definitions.state.collectAsStateWithLifecycle()
        TicketboxTheme(skin = AppSkin.valueOf(InstrumentationRegistry.getArguments().getString("ruleSkin") ?: "Paper")) {
            CategoryRulesScreen(CategoryRulesScreenState(
                CategoryRulesRuleListState(state.categoryRules, state.categoryRulesLoading, state.categoryRulesLoadFailed),
                CategoryRulesInteractionState(state.busy, !state.canModify), CategoryRulesStatusState(state.message, state.messageTone),
                CategoryRulesApplicationState(state.ruleApplications, state.ruleApplicationsLoading, state.confirmedRulesPreview,
                    state.ruleApplicationsLoadFailed, state.applicationReason, state.rollback),
                state.undoableRule, applicationSubmissions = state.pendingApplications, selectedSubmissionId = state.selectedSubmissionId,
                binding = state.binding, definitions = definitions),
                CategoryRulesScreenActions({}, CategoryRulesRuleActions(active::toggleCategoryRule, active::deleteCategoryRule,
                    active::recoverSubmission, { active.loadCategoryRules() }),
                    CategoryRulesApplicationActions(active::previewApplyConfirmedRules, active::confirmApplyConfirmedRules,
                        active::openRollback, { active.loadRuleApplications() }, active::recoverApplication,
                        active::changeApplicationReason, CategoryRuleRollbackActions(active::dismissRollback,
                            active::confirmRollback, active::refreshRollbackPreview, active::changeRollbackReason)),
                    CategoryRulesUndoActions(active::undoDelete, active::dismissUndo),
                    CategoryRuleDefinitionActions(active.definitions::begin, active.definitions::open, active.definitions::change,
                        active.definitions::submit, active.definitions::close, active.definitions::reviewBinding, active.definitions::reload)))
        }
    }
}

private class RuleApplicationConnectedNetwork {
    val keys = mutableListOf<String>()
    val applicationRequests = mutableListOf<RuleApplyConfirmedRequestDto>()
    val rollbackRequests = mutableListOf<Pair<String, String?>>()
    var applicationResponse: RuleApplyConfirmedResponseDto? = null
    var loseReply = true
    var failRead = true
    var reads = 0
    var showBatch = false
    var previewFails = true
    var rollbackLosesReply = true
    var rollbackAccepted = false
    private val rollbackResponse = RuleApplicationRollbackDto("accepted-batch", "rollback_partial", 1, 1,
        "2026-10-15T00:10:00Z", "核对后撤回本批次")
    private val rollbackReceipt get() = rollbackResponse.takeIf { rollbackAccepted }
    val api = object : ApiService by DebtAdjustmentConnectedNetwork().service {
        override suspend fun categoryRules(): List<CategoryRuleDto> = emptyList()
        override suspend fun ruleApplications(limit: Int) = RuleApplicationListDto(if (!showBatch) emptyList() else listOf(
            RuleApplicationBatchDto("accepted-batch", rollbackReceipt?.status ?: "applied_confirmed", 10, 2,
                "2026-10-15T00:00:00Z", rollbackReceipt?.rolledBackAt,
                if (rollbackReceipt == null) mapOf("applied" to 2) else mapOf("rolled_back" to 1, "skipped" to 1),
                "按商家统一分类", rollbackReceipt?.rollbackReason)))
        override suspend fun previewRuleApplicationRollback(publicId: String): RuleApplicationRollbackPreviewDto {
            if (previewFails) throw IOException("Synthetic preview unavailable")
            return RuleApplicationRollbackPreviewDto(publicId, 2, 1, 1, mapOf("modified_after_application" to 1),
                listOf(RuleRollbackSkippedItemDto(12, "已人工更正的小馆", "modified_after_application")))
        }
        override suspend fun rollbackRuleApplication(publicId: String, request: RuleApplicationRollbackRequestDto): RuleApplicationRollbackDto {
            rollbackRequests += publicId to request.reason
            if (rollbackLosesReply) throw IOException("Synthetic lost rollback reply")
            return rollbackResponse
        }
        override suspend fun confirmedExpenses(query: Map<String, String>): PaginatedExpensesDto {
            reads += 1
            if (failRead) throw IOException("Synthetic read failure after acceptance")
            return PaginatedExpensesDto(items = emptyList(), total = 0, page = 1, pageSize = 50)
        }
        override suspend fun applyConfirmedRules(request: RuleApplyConfirmedRequestDto, limit: Int, maxScan: Int,
            idempotencyKey: String?): RuleApplyConfirmedResponseDto {
            if (!request.confirm) return RuleApplyConfirmedResponseDto(true, 9, 1, previewToken = "original-preview", scanLimit = 500)
            val key = requireNotNull(idempotencyKey)
            keys += key
            applicationRequests += request
            if (loseReply) throw IOException("Synthetic lost application reply")
            return requireNotNull(applicationResponse)
        }
    }
}
