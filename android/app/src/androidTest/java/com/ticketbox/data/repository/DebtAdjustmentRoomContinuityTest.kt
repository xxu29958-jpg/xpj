package com.ticketbox.data.repository

import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.assertCountEquals
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasScrollToIndexAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performScrollToNode
import androidx.compose.ui.test.performTextReplacement
import androidx.compose.ui.test.performTouchInput
import androidx.compose.ui.test.click
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import androidx.test.espresso.Espresso.closeSoftKeyboard
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.R
import com.ticketbox.RepositoryGraph
import com.ticketbox.viewmodel.DebtAction
import com.ticketbox.ui.screens.DebtDetailScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.DebtDetailViewModel
import com.ticketbox.viewmodel.DebtActivityViewModel
import com.ticketbox.viewmodel.MemberRepaymentProposalViewModel
import com.ticketbox.viewmodel.OutboxRecoveryRepositories
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.outboxStatusViewModelFactory
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

class DebtAdjustmentRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val fixture = DebtAdjustmentConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    private val detail = mutableStateOf<DebtDetailViewModel?>(null)
    private lateinit var proposals: MemberRepaymentProposalViewModel
    private lateinit var history: DebtActivityViewModel

    @After
    fun close() { stopModels(); fixture.close() }

    @Test
    fun offlineKindSelectionSurvivesRoomReopenWithoutClaimingAChangedDebt() {
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        installModels()
        compose.setContent {
            val model = detail.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) { DebtDetailScreen(model, proposals, history, {}) }
        }
        compose.waitUntil(10_000) { detail.value?.state?.value?.canWriteActions == true }
        val originalDebt = fixture.network.current
        val originalBinding = requireNotNull(detail.value?.state?.value?.binding)
        val originalQueries = fixture.cachedDebtDetails()
        assertEquals("The displayed canonical debt must also be retained for offline re-entry", 1, originalQueries.size)
        assertEquals(originalDebt.publicId, originalQueries.single()["tag"])
        fixture.network.readFailure = java.net.SocketException("Synthetic offline debt read")
        fixture.network.failReads = true
        val editKind = context.getString(R.string.debt_kind_edit)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(editKind))
        compose.onNodeWithText(editKind).assertIsDisplayed().performClick()
        compose.onNodeWithText(context.getString(R.string.debt_kind_revolving)).performClick()
        compose.waitUntil(10_000) {
            detail.value?.state?.value?.isSubmitting == false &&
                (fixture.stored().isNotEmpty() || detail.value?.state?.value?.error != null)
        }
        assertEquals("The selected classification must remain a recoverable task while offline", 1, fixture.stored().size)
        val original = fixture.stored().single()
        assertEquals("debt:${originalDebt.publicId}", original["targetId"])
        assertEquals(originalDebt.rowVersion.toString(), original["expectedRowVersion"])
        assertTrue(!original["idempotencyKey"].isNullOrBlank())
        assertTrue(original["payload"].orEmpty().contains("revolving"))
        assertEquals(originalDebt, fixture.network.current)
        assertTrue(fixture.network.kindCalls.isEmpty())
        assertEquals(originalDebt.debtKind, detail.value?.state?.value?.debt?.debtKind)
        assertEquals("An unsent classification intent must preserve the last canonical read", originalQueries, fixture.cachedDebtDetails())
        stopModels()
        installModels()
        assertEquals(originalBinding, detail.value?.state?.value?.binding)
        assertEquals("Reopening Room must retain the same bound canonical read", originalQueries, fixture.cachedDebtDetails())
        compose.waitUntil(10_000) {
            detail.value?.state?.value?.let { it.pendingWrites.size == 1 && !it.isLoading } == true
        }
        assertEquals(listOf(original), fixture.stored())
        assertEquals(originalDebt.debtKind, detail.value?.state?.value?.debt?.debtKind)
        assertTrue(detail.value?.state?.value?.fromCache == true)
        val originalKind = context.getString(R.string.debt_kind_revolving)
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText(originalKind, substring = true))
        compose.onNodeWithText(originalKind, substring = true).assertIsDisplayed()
        settleOriginalKindAfterReopen(original)
    }

    private fun settleOriginalKindAfterReopen(original: Map<String, String?>) {
        fixture.network.kindResponse = fixture.network.current.copy(debtKind = "revolving", rowVersion = 3)
        fixture.network.failReads = false
        fixture.network.current = requireNotNull(fixture.network.kindResponse)
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        val accepted = fixture.network.current
        fixture.network.current = accepted.copy(debtKind = "installment", rowVersion = accepted.rowVersion + 1)
        fixture.network.failReads = true
        stopModels()
        installModels()
        compose.waitUntil(10_000) { detail.value?.state?.value?.pendingWrites?.singleOrNull()?.canRetry == true }
        fixture.network.loseResponse = false
        fixture.network.failReads = false
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        compose.onNodeWithText(context.getString(R.string.debt_write_retry)).performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.debtKind == "installment" }
        val completed = fixture.stored().single()
        for (column in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId")) {
            assertEquals(original[column], completed[column])
        }
        val receipt = com.ticketbox.OutboxAdapterGraph().debtVoidReceiptAdapter.fromJson(requireNotNull(completed["receiptJson"]))
        assertEquals(accepted, receipt)
        assertEquals("debt-original", fixture.network.kindCalls.first().first)
        assertEquals(original["idempotencyKey"], fixture.network.kindCalls.first().third)
        assertTrue(fixture.network.kindCalls.all { it == fixture.network.kindCalls.first() })
        compose.onNodeWithText(context.getString(R.string.debt_kind_confirmed)).performScrollTo().assertIsDisplayed()
    }

    @Test
    fun actualSaveAndRetryKeepTheOriginalAdjustmentAcrossRoomReopenAndFailedDetailRead() {
        installModels()
        compose.setContent {
            val model = detail.value ?: return@setContent
            TicketboxTheme(skin = AppSkin.Paper) { DebtDetailScreen(model, proposals, history, {}) }
        }
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt != null }
        compose.onNode(hasScrollToIndexAction()).performScrollToNode(hasText("调整本金"))
        compose.onNodeWithText("调整本金").assertIsDisplayed().performClick()
        compose.onAllNodes(hasSetTextAction()).assertCountEquals(2)
        compose.onAllNodes(hasSetTextAction())[0].performTextReplacement("30.00")
        compose.onAllNodes(hasSetTextAction())[1].performTextReplacement("补记原借款")
        // Finish text entry before hit-testing a button that moves with the IME insets.
        closeSoftKeyboard()
        compose.waitForIdle()
        compose.onNodeWithText("保存").assertIsDisplayed().assertIsEnabled()
            .performTouchInput { click() }
        compose.waitUntil(10_000) { fixture.stored().size == 1 && detail.value?.state?.value?.activeAction == null }
        val original = fixture.stored().single()
        assertEquals(0, fixture.network.calls.size)
        assertEquals(1, fixture.scheduleCalls)
        assertEquals(50_000L, detail.value?.state?.value?.debt?.remainingAmountCents)
        assertEquals("2", original["expectedRowVersion"])
        fixture.network.adjustmentResponse = fixture.network.current.copy(remainingAmountCents = 53_000, rowVersion = 3)
        fixture.network.current = requireNotNull(fixture.network.adjustmentResponse)
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)

        stopModels()
        fixture.network.failReads = true
        installModels()
        compose.waitUntil(10_000) { detail.value?.state?.value?.error != null &&
            detail.value?.state?.value?.pendingWrites?.size == 1 }
        for (key in listOf("payload", "expectedRowVersion", "idempotencyKey", "ownerKey", "ledgerId")) {
            assertEquals(original[key], fixture.stored().single()[key])
        }
        compose.onNodeWithText("补记原借款").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("重试原提交").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" && fixture.scheduleCalls == 2 }
        assertEquals(2, fixture.scheduleCalls)
        fixture.network.loseResponse = false
        fixture.network.failReads = false
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { detail.value?.state?.value?.debt?.rowVersion == 3L }
        assertEquals(53_000L, detail.value?.state?.value?.debt?.remainingAmountCents)
        assertEquals(fixture.network.calls.first(), fixture.network.calls.last())
        assertEquals("debt-original", fixture.network.calls.last().first)
        assertEquals(original["idempotencyKey"], fixture.network.calls.last().third)
        assertEquals(emptyList<PendingDebtWrite>(), detail.value?.state?.value?.pendingWrites)
    }

    @Test
    fun retainedConsumersRefreshAfterBackgroundAdjustmentDelivery() {
        fixture.network.current = fixture.network.current.copy(direction = "owed_to_me")
        fixture.network.loseResponse = false
        val graph = fixture.reopen()
        lateinit var retained: RetainedAdjustmentConsumers
        compose.runOnIdle { retained = RetainedAdjustmentConsumers(graph) }
        try {
            compose.waitUntil(10_000) { retained.balances() == List(5) { 50_000L } }
            compose.runOnIdle {
                retained.createGoal.updateName("保留原目标名称")
                retained.createGoal.toggleDebt(fixture.network.current.publicId)
            }
            saveAndCloseDetail(graph, fixture)
            val original = fixture.stored().single()
            assertEquals(1, runBlocking { fixture.drain() }.done)
            assertEquals("done", fixture.stored().single()["status"])
            compose.waitUntil(10_000) { retained.balances() == List(5) { 53_000L } }
            assertEquals("list, receivables, goal, create goal and repayment draft", List(5) { 53_000L }, retained.balances())
            assertRetainedAdjustmentSelection(retained.createGoal, fixture.network.current.publicId)
            assertRetainedAdjustmentSelection(retained.inbox, fixture.network.current.publicId)
            for (field in listOf("payload", "expectedRowVersion", "idempotencyKey", "ownerKey", "ledgerId")) {
                assertEquals(original[field], fixture.stored().single()[field])
            }
        } finally { compose.runOnIdle { retained.close() } }
    }

    @Test
    fun globalDropOfUnknownAdjustmentRequiresCanonicalRecoveryForAllRetainedConsumers() {
        fixture.network.current = fixture.network.current.copy(direction = "owed_to_me")
        val graph = fixture.reopen()
        var retained: RetainedAdjustmentConsumers? = null
        var global: OutboxStatusViewModel? = null
        val gate = CompletableDeferred<Unit>()
        try {
            compose.runOnIdle {
                retained = RetainedAdjustmentConsumers(graph)
                global = outboxStatusViewModelFactory(fixture.outbox, graph.expenseRepository,
                    OutboxRecoveryRepositories(graph.debtCreationRepository, graph.recurringRepository.occurrences,
                        graph.incomePlanRepository, graph.debtWriteRepository, graph.goalEditRepository, graph.budgetRepository, graph.recurringRepository, graph.ruleRepository, repaymentReviews = graph.repaymentReviewRepository)).create(OutboxStatusViewModel::class.java)
            }
            val consumers = requireNotNull(retained)
            val sync = requireNotNull(global)
            compose.waitUntil(10_000) { consumers.balances() == List(5) { 50_000L } }
            compose.runOnIdle {
                consumers.createGoal.updateName("保留原目标名称")
                consumers.createGoal.toggleDebt(fixture.network.current.publicId)
            }
            saveAndCloseDetail(graph, fixture)
            val original = fixture.stored().single()
            assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
            assertEquals(53_000L, fixture.network.current.remainingAmountCents)
            compose.waitUntil(10_000) { sync.uiState.value.status.failed.size == 1 }
            for (field in listOf("payload", "expectedRowVersion", "idempotencyKey", "ownerKey", "ledgerId")) {
                assertEquals(original[field], fixture.stored().single()[field])
            }
            fixture.network.failReads = true
            fixture.network.readGate = gate
            compose.runOnIdle { sync.dropFailed(sync.uiState.value.status.failed.single()) }
            compose.waitUntil(10_000) { sync.uiState.value.status.failed.isEmpty() }
            compose.waitUntil(10_000) { !consumers.createGoal.state.value.canSubmit &&
                consumers.inbox.state.value.targetDebts.isEmpty() }
            compose.runOnIdle {
                assertFalse(consumers.createGoal.state.value.canSubmit)
                assertTrue(consumers.inbox.state.value.targetDebts.isEmpty())
            }
            gate.complete(Unit)
            compose.waitUntil(10_000) { consumers.allReadsFailed() }
            assertFalse(consumers.createGoal.state.value.canSubmit)
            assertTrue(consumers.inbox.state.value.targetDebts.isEmpty())
            fixture.network.failReads = false
            fixture.network.readGate = null
            compose.runOnIdle { consumers.refresh() }
            try {
                compose.waitUntil(10_000) { consumers.balances() == List(5) { 53_000L } }
            } catch (failure: androidx.compose.ui.test.ComposeTimeoutException) {
                throw AssertionError("Recovered balances (list, receivables, goal, create goal, inbox): ${consumers.balances()}", failure)
            }
            assertRetainedAdjustmentSelection(consumers.createGoal, fixture.network.current.publicId)
            assertRetainedAdjustmentSelection(consumers.inbox, fixture.network.current.publicId)
            assertTrue(consumers.createGoal.state.value.canSubmit)
            fixture.stored().singleOrNull()?.let { abandoned ->
                for (field in listOf("payload", "expectedRowVersion", "idempotencyKey", "ownerKey", "ledgerId")) {
                    assertEquals(original[field], abandoned[field])
                }
                assertTrue(abandoned["status"] != "done")
            }
            assertEquals(0, runBlocking { fixture.drain() }.done)
            assertEquals(1, fixture.network.calls.size)
            assertEquals("debt-original", fixture.network.calls.single().first)
            assertEquals(original["idempotencyKey"], fixture.network.calls.single().third)
            assertEquals(2, fixture.scheduleCalls)
        } finally {
            gate.complete(Unit)
            compose.runOnIdle { retained?.close(); global?.viewModelScope?.cancel() }
        }
    }

    private fun saveAndCloseDetail(graph: RepositoryGraph, retained: DebtAdjustmentConnectedFixture) {
        retained.network.adjustmentResponse = retained.network.current.copy(remainingAmountCents = 53_000, rowVersion = 3)
        lateinit var model: DebtDetailViewModel
        compose.runOnIdle {
            model = DebtDetailViewModel(graph.debtRepository, graph.debtWriteRepository)
            model.loadDebt(retained.network.current.publicId)
        }
        compose.waitUntil(10_000) { model.state.value.debt != null }
        compose.runOnIdle {
            model.openAction(DebtAction.Adjustment)
            model.updateActionInput(amount = "30", reason = "补记原借款")
            model.submit()
        }
        compose.waitUntil(10_000) { retained.stored().size == 1 && model.state.value.activeAction == null }
        compose.runOnIdle { model.viewModelScope.cancel() }
        retained.network.current = requireNotNull(retained.network.adjustmentResponse)
    }

    @Test fun originalAdjustmentFromPreviousSessionRemainsReadableWithoutDetailOrGlobalRetry() {
        assertChangedOriginCannotResume(changeSession = true)
    }

    @Test fun originalAdjustmentFromPreviousBindingRevisionRemainsReadableWithoutDetailOrGlobalRetry() {
        assertChangedOriginCannotResume(changeSession = false)
    }

    private fun assertChangedOriginCannotResume(changeSession: Boolean) {
        val originalGraph = fixture.reopen()
        val binding = requireNotNull(originalGraph.debtWriteRepository.currentAccess()).binding
        runBlocking { originalGraph.debtWriteRepository.save(binding, fixture.network.current.toDomain(), 3_000, "补记原借款").getOrThrow() }
        fixture.network.adjustmentResponse = fixture.network.current.copy(remainingAmountCents = 53_000, rowVersion = 3)
        fixture.network.current = requireNotNull(fixture.network.adjustmentResponse)
        fixture.network.loseResponse = true
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        val original = fixture.stored().single()
        fixture.session = if (changeSession) fixture.session.copy(sessionGeneration = "new-session")
            else fixture.session.copy(bindingRevision = "new-revision")
        installModels()
        compose.setContent { detail.value?.let { model ->
            TicketboxTheme(skin = AppSkin.Paper) { DebtDetailScreen(model, proposals, history, {}) }
        } }
        compose.waitUntil(10_000) { detail.value?.state?.value?.pendingWrites?.singleOrNull() != null }
        val state = requireNotNull(detail.value).state.value
        val pending = state.pendingWrites.single()
        assertNotNull(pending.intent)
        compose.onNodeWithText("原调整金额：", substring = true).performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("补记原借款").assertExists()
        compose.onNodeWithText(InstrumentationRegistry.getInstrumentation().targetContext.getString(R.string.debt_write_original_binding_changed).substringBefore('，'),
            substring = true).assertExists()
        compose.onNodeWithText("重试原提交").assertDoesNotExist()
        assertFalse(pending.canRetry)
        assertTrue(runBlocking { fixture.graph.debtWriteRepository.recover(requireNotNull(state.binding), pending, false) }.isFailure)
        assertEquals(original, fixture.stored().single())
        assertEquals(0, runBlocking { fixture.drain() }.attempted)
        lateinit var sync: OutboxStatusViewModel
        compose.runOnIdle { sync = outboxStatusViewModelFactory(fixture.outbox, fixture.graph.expenseRepository,
            OutboxRecoveryRepositories(fixture.graph.debtCreationRepository, fixture.graph.recurringRepository.occurrences,
                fixture.graph.incomePlanRepository, fixture.graph.debtWriteRepository, fixture.graph.goalEditRepository,
                fixture.graph.budgetRepository, fixture.graph.recurringRepository, fixture.graph.ruleRepository, repaymentReviews = fixture.graph.repaymentReviewRepository))
            .create(OutboxStatusViewModel::class.java) }
        try {
            compose.waitUntil(10_000) { sync.uiState.value.status.failed.size == 1 }
            val failed = sync.uiState.value.status.failed.single()
            assertFalse(sync.uiState.value.offersRetry(failed))
            compose.runOnIdle { sync.retry(failed) }
            compose.waitUntil(10_000) { sync.uiState.value.message != null }
            assertEquals(original, fixture.stored().single())
            assertEquals(1, fixture.network.calls.size)
            compose.runOnIdle { sync.dropFailed(failed) }
            compose.waitUntil(10_000) { fixture.stored().single()["status"] == "abandoned" }
            for (field in listOf("payload", "idempotencyKey", "expectedRowVersion", "targetId", "ownerKey", "ledgerId", "serverUrl", "createdAt")) {
                assertEquals(original[field], fixture.stored().single()[field])
            }
            assertEquals(0, runBlocking { fixture.drain() }.attempted)
        } finally { compose.runOnIdle { sync.viewModelScope.cancel() } }
    }

    private fun installModels() {
        val graph = fixture.reopen()
        compose.runOnIdle {
            proposals = MemberRepaymentProposalViewModel(graph.debtRepository.proposals)
            history = DebtActivityViewModel(graph.debtRepository.activity)
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
