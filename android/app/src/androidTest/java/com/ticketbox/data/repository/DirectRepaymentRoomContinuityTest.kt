package com.ticketbox.data.repository

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.screens.DebtDetailScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.DebtRepaymentHistoryViewModel
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import com.ticketbox.viewmodel.OutboxRecoveryRepositories
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.outboxStatusViewModelFactory
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class DirectRepaymentRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private val fixture = DebtAdjustmentConnectedFixture(context)
    private val detail = mutableStateOf<DebtDetailViewModel?>(null)
    private lateinit var proposals: MemberRepaymentProposalViewModel
    private lateinit var history: DebtRepaymentHistoryViewModel

    @After fun close() { stopModels(); fixture.close() }

    @Test fun actualSaveLostAckRoomReopenAndOriginalRetryKeepOneRepaymentWhileCanonicalReadFails() {
        installModels()
        compose.setContent {
            val model = detail.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) { DebtDetailScreen(model, proposals, history, {}) }
        }
        compose.waitUntil(10_000) { detail.value?.state?.value?.canWriteActions == true }
        compose.onNodeWithText("记还款").performScrollTo().performClick()
        compose.onAllNodes(hasSetTextAction()).assertCountEquals(1)
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("100.00")
        compose.onNodeWithText("保存").performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 && detail.value?.state?.value?.activeAction == null }
        val original = fixture.stored().single()
        assertEquals(0, fixture.network.repaymentCalls.size)
        assertEquals(1, fixture.scheduleCalls)
        assertEquals(50_000L, detail.value?.state?.value?.debt?.remainingAmountCents)
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        assertEquals(1, fixture.network.repaymentResults.size)

        stopModels()
        fixture.network.failReads = true
        installModels()
        compose.waitUntil(10_000) { detail.value?.state?.value?.error != null &&
            detail.value?.state?.value?.pendingWrites?.size == 1 }
        assertOriginalColumns(original)
        val pending = requireNotNull(detail.value?.state?.value?.pendingWrites?.single()?.repayment)
        assertEquals(10_000L, pending.request.amountCents)
        assertEquals(2L, pending.request.expectedRowVersion)
        compose.onNodeWithText("原还款金额：", substring = true).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("原还款时间：", substring = true).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("重试原提交").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" && fixture.scheduleCalls == 2 }
        fixture.network.loseResponse = false
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { detail.value?.state?.value?.pendingWrites?.singleOrNull()?.row?.receiptJson != null }
        compose.onNodeWithText(context.getString(R.string.debt_repayment_confirmed)).performScrollTo().assertIsDisplayed()
        assertFalse(requireNotNull(detail.value).state.value.canWriteActions)
        assertNotNull(fixture.stored().single()["receiptJson"])
        assertOriginalColumns(original)
        assertEquals(fixture.network.repaymentCalls.first(), fixture.network.repaymentCalls.last())
        assertEquals(1, fixture.network.repaymentResults.size)

        fixture.network.failReads = false
        compose.runOnIdle { detail.value?.refresh() }
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.rowVersion == 3L && history.state.value.items.size == 1 }
        assertEquals(40_000L, detail.value?.state?.value?.debt?.remainingAmountCents)
        assertEquals("repayment-1", history.state.value.items.single().publicId)
        assertEquals(pending.request.paidAt, history.state.value.items.single().paidAt)
        assertTrue(requireNotNull(detail.value).state.value.canWriteActions)
        assertEquals(2, fixture.network.repaymentCalls.size)
    }

    @Test fun backgroundRepaymentRefreshesAllFiveRetainedConsumersAndGlobalStopPreservesUnknownOriginal() {
        fixture.network.current = fixture.network.current.copy(direction = "owed_to_me")
        val graph = fixture.reopen()
        lateinit var retained: RetainedAdjustmentConsumers
        lateinit var sync: OutboxStatusViewModel
        compose.runOnIdle {
            retained = RetainedAdjustmentConsumers(graph)
            sync = outboxStatusViewModelFactory(fixture.outbox, graph.expenseRepository,
                OutboxRecoveryRepositories(graph.debtCreationRepository, graph.recurringRepository.occurrences,
                    graph.incomePlanRepository, graph.debtWriteRepository, graph.goalEditRepository, graph.budgetRepository,
                    graph.recurringRepository, graph.ruleRepository)).create(OutboxStatusViewModel::class.java)
        }
        try {
            compose.waitUntil(10_000) { retained.balances() == List(5) { 50_000L } }
            compose.runOnIdle {
                retained.createGoal.updateName("保留原目标名称")
                retained.createGoal.toggleDebt(fixture.network.current.publicId)
            }
            val binding = requireNotNull(graph.debtWriteRepository.currentAccess()).binding
            runBlocking { graph.debtWriteRepository.saveRepayment(binding, fixture.network.current.toDomain(), 10_000).getOrThrow() }
            assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
            compose.waitUntil(10_000) { sync.uiState.value.status.failed.size == 1 }
            compose.runOnIdle { sync.retry(sync.uiState.value.status.failed.single()) }
            compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
            fixture.network.loseResponse = false
            assertEquals(1, runBlocking { fixture.drain() }.done)
            compose.waitUntil(10_000) { retained.balances() == List(5) { 40_000L } }
            assertRetainedAdjustmentSelection(retained.createGoal, fixture.network.current.publicId)
            assertRetainedAdjustmentSelection(retained.inbox, fixture.network.current.publicId)

            runBlocking { graph.debtWriteRepository.saveRepayment(binding, fixture.network.current.toDomain(), 5_000).getOrThrow() }
            fixture.network.loseResponse = true
            assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
            val second = fixture.stored().last()
            compose.waitUntil(10_000) { sync.uiState.value.status.failed.size == 1 }
            fixture.network.failReads = true
            compose.runOnIdle { sync.dropFailed(sync.uiState.value.status.failed.single()) }
            compose.waitUntil(10_000) { fixture.stored().last()["status"] == "abandoned" && retained.allReadsFailed() }
            assertFalse(retained.createGoal.state.value.canSubmit)
            assertTrue(retained.inbox.state.value.targetDebts.isEmpty())
            for (field in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId")) {
                assertEquals(second[field], fixture.stored().last()[field])
            }
            assertEquals(0, runBlocking { fixture.drain() }.attempted)
            fixture.network.failReads = false
            compose.runOnIdle { retained.refresh() }
            compose.waitUntil(10_000) { retained.balances() == List(5) { 35_000L } }
            assertEquals(2, fixture.network.repaymentResults.size)
            assertEquals(3, fixture.network.repaymentCalls.size)
        } finally {
            compose.runOnIdle { retained.close(); sync.viewModelScope.cancel() }
        }
    }

    private fun assertOriginalColumns(original: Map<String, String?>) {
        for (field in listOf("payload", "expectedRowVersion", "idempotencyKey", "ownerKey", "ledgerId", "serverUrl", "createdAt")) {
            assertEquals(original[field], fixture.stored().single()[field])
        }
    }

    private fun installModels() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            proposals = MemberRepaymentProposalViewModel(graph.debtRepository.proposals)
            history = DebtRepaymentHistoryViewModel(graph.debtRepository.repayments)
            detail.value = DebtDetailViewModel(graph.debtRepository, graph.debtWriteRepository)
                .also { it.loadDebt(fixture.network.current.publicId) }
        }
    }

    private fun stopModels() = compose.runOnIdle {
        detail.value?.viewModelScope?.cancel()
        if (::proposals.isInitialized) proposals.viewModelScope.cancel()
        if (::history.isInitialized) history.viewModelScope.cancel()
    }
}
