package com.ticketbox.data.repository

import androidx.compose.runtime.getValue
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextInput
import androidx.lifecycle.compose.collectAsStateWithLifecycle
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.CategoryRuleDto
import com.ticketbox.data.remote.dto.CategoryRuleRequest
import com.ticketbox.data.remote.dto.RuleApplicationListDto
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.settings.CategoryRulesScreen
import com.ticketbox.ui.screens.settings.CategoryRulesScreenState
import com.ticketbox.ui.screens.settings.CategoryRulesRuleListState
import com.ticketbox.ui.screens.settings.CategoryRulesInteractionState
import com.ticketbox.ui.screens.settings.CategoryRulesStatusState
import com.ticketbox.ui.screens.settings.CategoryRulesApplicationState
import com.ticketbox.ui.screens.settings.CategoryRulesScreenActions
import com.ticketbox.ui.screens.settings.CategoryRulesRuleActions
import com.ticketbox.ui.screens.settings.CategoryRulesApplicationActions
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

class CategoryRuleSubmissionConnectedTest {
    @get:Rule val compose = createComposeRule()
    private val network = DebtAdjustmentConnectedNetwork()
    private var loseAck = true
    private val keys = mutableListOf<String>()
    private val accepted = mutableMapOf<String, CategoryRuleDto>()
    private val api = object : ApiService by network.service {
        override suspend fun categoryRules(): List<CategoryRuleDto> = emptyList()
        override suspend fun ruleApplications(limit: Int) = RuleApplicationListDto(emptyList())
        override suspend fun createCategoryRule(request: CategoryRuleRequest, idempotencyKey: String): CategoryRuleDto {
            keys += idempotencyKey
            check(request.homeCurrencyCode == "JPY" && request.amountMinCents == 1200L)
            val result = accepted.getOrPut(idempotencyKey) { CategoryRuleDto(7, requireNotNull(request.keyword),
                requireNotNull(request.category), true, 10, request.amountMinCents, request.amountMaxCents,
                createdAt = "2026-09-09T00:00:00Z", updatedAt = "2026-09-09T00:00:00Z", rowVersion = 1,
                homeCurrencyCode = request.homeCurrencyCode) }
            if (loseAck) throw IOException("Synthetic lost acknowledgement")
            return result
        }
    }
    private val fixture = DebtAdjustmentConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext, api)
    private lateinit var model: CategoryRulesViewModel

    @After fun close() {
        if (::model.isInitialized) compose.runOnIdle { model.viewModelScope.cancel() }
        fixture.close()
    }

    @Test fun realRuleAmountEditorPublishesJpyThenReopensAndReplaysTheSameReceipt() {
        val graph = fixture.reopen()
        model = CategoryRulesViewModel(graph.ruleRepository, graph.expenseRepository)
        showScreen()
        compose.onNodeWithText("添加规则").performClick()
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextInput("旅行")
        compose.onAllNodes(hasSetTextAction())[1].performScrollTo().performTextInput("交通")
        compose.onNodeWithText("选择金额币种").performScrollTo().performClick()
        compose.onNodeWithText("JPY · 日元").performClick()
        compose.onAllNodes(hasSetTextAction())[3].performScrollTo().performTextInput("1200")
        compose.onNodeWithText("添加规则").performScrollTo().performClick()
        compose.waitUntil(10_000) { model.uiState.value.pendingSubmissions.isNotEmpty() }
        val original = fixture.stored().single()
        assertEquals(emptyList<String>(), keys)
        compose.runOnIdle { model.viewModelScope.cancel() }
        val reopened = fixture.reopen()
        assertEquals(original, fixture.stored().single())
        val adapters = OutboxAdapterGraph()
        val engine = OutboxDrainEngine(fixture.outbox, listOf(CategoryRuleDispatcher(PendingMutationType.CreateCategoryRule,
            { api }, adapters.categoryRuleSubmissionAdapter, adapters.categoryRuleReceiptAdapter)), maxAttempts = 1)
        runBlocking {
            assertEquals(1, engine.drainOnce().failures)
            val owner = reopened.ruleRepository
            val pending = owner.describeSubmission(fixture.outbox.observeStatus().first().failed.single())!!
            owner.recoverSubmission(owner.currentAccess()!!.binding, pending, false).getOrThrow()
            loseAck = false
            assertEquals(1, engine.drainOnce().done)
        }
        assertEquals(listOf(original["idempotencyKey"], original["idempotencyKey"]), keys)
        assertEquals(1, accepted.size)
        assertEquals(original["payload"], fixture.stored().single()["payload"])
    }

    private fun showScreen() = compose.setContent {
        val state by model.uiState.collectAsStateWithLifecycle()
        TicketboxTheme(skin = AppSkin.Paper) {
            CategoryRulesScreen(CategoryRulesScreenState(
                CategoryRulesRuleListState(state.categoryRules, state.categoryRulesLoading),
                CategoryRulesInteractionState(state.busy, false), CategoryRulesStatusState(state.message, state.messageTone),
                CategoryRulesApplicationState(state.ruleApplications, state.ruleApplicationsLoading, state.confirmedRulesPreview),
                state.undoableRule, state.pendingSubmissions, state.selectedSubmissionId, state.submittedRevision, state.binding),
                CategoryRulesScreenActions({}, CategoryRulesRuleActions(model::createCategoryRule, model::updateCategoryRule,
                    model::toggleCategoryRule, model::deleteCategoryRule, model::recoverSubmission),
                    CategoryRulesApplicationActions({}, {}, {}), CategoryRulesUndoActions({}, {})))
        }
    }
}
