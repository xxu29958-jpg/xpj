package com.ticketbox.data.repository

import androidx.compose.runtime.getValue
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.mutableStateOf
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsNotEnabled
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performScrollTo
import androidx.compose.ui.test.performTextReplacement
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import com.ticketbox.ui.screens.expense.fact.ExpenseFactScreen
import com.ticketbox.ui.screens.settings.SyncStatusScreen
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.ExpenseDetailDataLoadState
import com.ticketbox.viewmodel.ExpenseFactViewModel
import com.ticketbox.viewmodel.OutboxRecoveryRepositories
import com.ticketbox.viewmodel.OutboxStatusViewModel
import com.ticketbox.viewmodel.outboxStatusViewModelFactory
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Actual Save and Retry UI, disk Room reopen and shared sender. Transport models response loss; no real process death or PG. */
class ExpenseCorrectionRoomContinuityTest {
    @get:Rule val compose = createComposeRule()
    private val fixture = ExpenseCorrectionConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext)
    private val model = mutableStateOf<ExpenseFactViewModel?>(null)
    private var global: OutboxStatusViewModel? = null

    @After fun close() { stopModel(); compose.runOnIdle { global?.viewModelScope?.cancel() }; fixture.close() }

    @Test
    fun realDetailSaveReopensOriginalSubmissionAndRetriesLostResponseWithoutForgingFact() {
        installModel()
        compose.setContent {
            val vm = model.value ?: return@setContent
            val state by vm.uiState.collectAsState()
            TicketboxTheme(skin = AppSkin.Paper) { ExpenseFactScreen(state, vm, {}) }
        }
        compose.waitUntil(10_000) { model.value?.uiState?.value?.expenseLoadState == ExpenseDetailDataLoadState.Loaded }
        compose.onNodeWithText("更正这笔账单").performScrollTo().performClick()
        compose.onAllNodes(hasSetTextAction())[0].performScrollTo().performTextReplacement("核对原小票")
        compose.onNode(hasSetTextAction() and hasText("10.00")).performScrollTo().performTextReplacement("12.00")
        compose.onNodeWithText("保存更正").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 && model.value?.uiState?.value?.corrections?.size == 1 }
        val original = fixture.stored().single()
        assertEquals(0, fixture.network.calls.size)
        assertEquals(1, fixture.schedules)
        assertEquals(1_000L, model.value?.uiState?.value?.expense?.amountCents)
        assertEquals(1, runBlocking { fixture.drain(maxAttempts = 1) }.failures)
        assertEquals(1, fixture.network.results.size)
        stopModel()
        fixture.network.failReads = true
        installModel()
        compose.waitUntil(10_000) { model.value?.uiState?.value?.corrections?.singleOrNull()?.canRetry == true }
        for (column in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId")) {
            assertEquals(original[column], fixture.stored().single()[column])
        }
        compose.onNodeWithText("原因：核对原小票").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("重试原提交").performScrollTo().performClick()
        compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
        finishOriginalReplay(original)
    }

    @Test
    fun realRoomCascadeAndGenericRecoveryKeepOriginalCorrectionIdentity() = runBlocking {
        val graph = fixture.reopen()
        val repository = graph.expenseRepository
        val access = requireNotNull(repository.observeCorrections().first().access)
        val id = repository.submitCorrection(access.binding, fixture.network.current.toDomain(),
            ExpenseCorrectionDraft("原意图", note = "不要换版本")).getOrThrow()
        val original = fixture.stored().single()
        fixture.outbox.cascadeFreshToken("expense:42", 8)
        fixture.outbox.markConflict(id, "state_conflict")
        assertFalse(fixture.outbox.resolveConflict(id, ConflictResolution.KeepMine(8)))
        fixture.outbox.markFailed(id, "runtime_version_mismatch")
        assertFalse(fixture.outbox.resolveFailed(id, FailedResolution.Retry(freshToken = 8)))
        for (column in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId")) {
            assertEquals(original[column], fixture.stored().single()[column])
        }
        fixture.role("viewer")
        assertTrue(repository.recoverCorrection(access.binding, id, false).isFailure)
        fixture.switchLedger()
        assertTrue(repository.observeCorrections().first().corrections.isEmpty())
        assertTrue(repository.recoverCorrection(access.binding, id, true).isFailure)
        assertEquals(1, fixture.stored().size)
        assertEquals(0, fixture.network.calls.size)
    }

    @Test
    fun sharedGlobalConsumerShowsOriginalAndViewerCannotRetry() {
        val graph = fixture.reopen()
        runBlocking {
            val access = requireNotNull(graph.expenseRepository.observeCorrections().first().access)
            val id = graph.expenseRepository.submitCorrection(access.binding, fixture.network.current.toDomain(),
                ExpenseCorrectionDraft("全局恢复原提交", note = "原备注")).getOrThrow()
            fixture.outbox.markFailed(id, "correction_delivery_unknown")
        }
        fixture.role("viewer")
        fixture.network.failReads = true
        var opened: Long? = null
        compose.runOnIdle {
            global = outboxStatusViewModelFactory(fixture.outbox, graph.expenseRepository,
                OutboxRecoveryRepositories(graph.debtCreationRepository, graph.recurringRepository.occurrences,
                    graph.incomePlanRepository, graph.debtAdjustmentRepository)).create(OutboxStatusViewModel::class.java)
        }
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) {
            SyncStatusScreen(requireNotNull(global), {}, onOpenExpense = { opened = it }, onOpenInbox = {})
        } }
        compose.waitUntil(10_000) { global?.uiState?.value?.correctionObservation?.corrections?.size == 1 }
        compose.onNodeWithText("原因：全局恢复原提交").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("重试原提交").performScrollTo().assertIsNotEnabled()
        compose.onNodeWithText("刷新并核对当前事实").performScrollTo().performClick()
        assertEquals(42L, opened)
        compose.runOnIdle { global?.retry(requireNotNull(global).uiState.value.correctionObservation.corrections.single().row) }
        compose.waitUntil(10_000) { global?.uiState?.value?.message != null }
        assertEquals("failed", fixture.stored().single()["status"])
        assertEquals(0, fixture.network.calls.size)
    }

    @Test
    fun androidUnicodeAdmissionKeepsTheOriginalRequestInRoom() = runBlocking {
        val boundaries = listOf(
            Triple("sharp s", "ß".repeat(32), "ß".repeat(33)),
            Triple("capital sharp s", "ẞ".repeat(32), "ẞ".repeat(33)),
            Triple("supplementary character", "\uD83D\uDE42".repeat(64), "\uD83D\uDE42".repeat(65)),
            Triple("NEXT LINE whitespace", "a".repeat(31) + "\u0085".repeat(5) + "b".repeat(32),
                "a".repeat(32) + "\u0085".repeat(5) + "b".repeat(32)),
        )
        for ((label, accepted, refused) in boundaries) {
            val repository = fixture.reopen().expenseRepository
            try {
                val binding = requireNotNull(repository.observeCorrections().first().access).binding
                val baseline = fixture.network.current.toDomain()
                val schedulesBefore = fixture.schedules
                assertTrue(label, repository.submitCorrection(binding, baseline,
                    ExpenseCorrectionDraft("核对标签", tags = refused)).isFailure)
                assertTrue(label, fixture.stored().isEmpty())
                assertEquals(label, schedulesBefore, fixture.schedules)
                val id = repository.submitCorrection(binding, baseline,
                    ExpenseCorrectionDraft("核对标签", tags = accepted)).getOrThrow()
                val original = fixture.stored().single()
                val pending = fixture.reopen().expenseRepository.observeCorrections().first().corrections.single()
                assertEquals(label, id, pending.row.id)
                assertEquals(label, accepted, requireNotNull(pending.intent).request.tags)
                assertEquals(label, baseline.rowVersion, pending.row.expectedRowVersion)
                assertEquals(label, binding.ownerKey, pending.row.ownerKey)
                assertEquals(label, binding.ledgerId, pending.row.ledgerId)
                assertFalse(label, pending.row.idempotencyKey.isNullOrBlank())
                assertEquals(label, original, fixture.stored().single())
                assertEquals(label, schedulesBefore + 1, fixture.schedules)
                assertEquals(label, 0, fixture.network.calls.size)
            } finally {
                // Isolate each literal boundary in the same real Room fixture, without fabricating delivery.
                fixture.close()
            }
        }
    }

    @Test
    fun sharedCorrectionRecoveryExplainsProtocolRefusalWithoutChangingOriginalCommand() {
        val graph = fixture.reopen()
        runBlocking {
            val access = requireNotNull(graph.expenseRepository.observeCorrections().first().access)
            graph.expenseRepository.submitCorrection(access.binding, fixture.network.current.toDomain(),
                ExpenseCorrectionDraft("核对协议拒绝原提交", note = "保留原备注")).getOrThrow()
        }
        val original = fixture.stored().single()
        compose.runOnIdle {
            global = outboxStatusViewModelFactory(fixture.outbox, graph.expenseRepository,
                OutboxRecoveryRepositories(graph.debtCreationRepository, graph.recurringRepository.occurrences,
                    graph.incomePlanRepository, graph.debtAdjustmentRepository)).create(OutboxStatusViewModel::class.java)
        }
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) {
            SyncStatusScreen(requireNotNull(global), {}, onOpenExpense = {}, onOpenInbox = {})
        } }
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        for (code in listOf("runtime_version_mismatch", "client_upgrade_required")) {
            fixture.network.refusalCode = code
            assertEquals(1, runBlocking { fixture.drain() }.failures)
            compose.waitUntil(10_000) { global?.uiState?.value?.correctionObservation?.corrections
                ?.singleOrNull()?.row?.lastError == code }
            compose.onNodeWithText(context.getString(R.string.sync_status_error_protocol_mismatch))
                .performScrollTo().assertIsDisplayed()
            compose.onNodeWithText(code).assertDoesNotExist()
            compose.onNodeWithText("private transport detail").assertDoesNotExist()
            compose.onNodeWithText(context.getString(R.string.correction_submission_failed)).assertDoesNotExist()
            compose.onNodeWithText("重试原提交").performScrollTo().performClick()
            compose.waitUntil(10_000) { fixture.stored().single()["status"] == "pending" }
            for (column in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId")) {
                assertEquals(original[column], fixture.stored().single()[column])
            }
        }
        assertEquals(2, fixture.network.calls.size)
        fixture.network.calls.forEach { (request, key) ->
            assertEquals(7L, request.expectedRowVersion)
            assertEquals(original["idempotencyKey"], key)
        }
        assertTrue(fixture.network.results.isEmpty())
        assertEquals(1_000L, fixture.network.current.amountCents)
        assertEquals(0, fixture.confirmedCallbacks)
        assertEquals(0, fixture.adviceCallbacks)
    }

    @Test
    fun legacyDoneSurvivesReopenAsReviewRequiredAndCanOnlyBeExplicitlyDiscarded() = runBlocking {
        fixture.reopen()
        val id = fixture.outbox.enqueue(PendingMutationType.CorrectExpense, "expense:42",
            """{"expected_row_version":0,"reason":"旧提交","splits":[]}""", 9, "old-key")
        fixture.outbox.markDone(id)
        val original = fixture.stored().single()
        val graph = fixture.reopen()
        val repository = graph.expenseRepository
        val observed = repository.observeCorrections().first()
        val pending = observed.corrections.single()
        assertFalse(pending.delivered)
        assertFalse(pending.canRetry)
        assertEquals("旧提交", pending.legacyRequest?.reason)
        assertEquals(original["payload"], fixture.stored().single()["payload"])
        val binding = requireNotNull(observed.access).binding
        assertTrue(repository.recoverCorrection(binding, id, false).isFailure)
        compose.runOnIdle {
            global = outboxStatusViewModelFactory(fixture.outbox, repository,
                OutboxRecoveryRepositories(graph.debtCreationRepository, graph.recurringRepository.occurrences,
                    graph.incomePlanRepository, graph.debtAdjustmentRepository)).create(OutboxStatusViewModel::class.java)
        }
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) {
            SyncStatusScreen(requireNotNull(global), {}, onOpenExpense = {}, onOpenInbox = {})
        } }
        compose.waitUntil(10_000) { global?.uiState?.value?.correctionObservation?.corrections?.singleOrNull()?.row?.id == id }
        val status = requireNotNull(global).uiState.value.status
        assertEquals(0, status.queueDepth)
        assertTrue(status.conflicts.isEmpty())
        assertTrue(status.failed.isEmpty())
        assertEquals(0, status.quarantinedCount)
        val context = InstrumentationRegistry.getInstrumentation().targetContext
        compose.onNodeWithText(context.getString(R.string.correction_submission_unsupported))
            .performScrollTo().assertIsDisplayed()
        compose.onNodeWithText(context.getString(R.string.correction_submission_retry)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.sync_status_overview_caption_settled)).assertDoesNotExist()
        compose.onNodeWithText(context.getString(R.string.sync_status_overview_caption_needs_action, 1)).assertDoesNotExist()
        compose.onNodeWithText("1 笔旧提交需要核对当前事实，送达情况尚未确认。")
            .performScrollTo().assertIsDisplayed()
        assertEquals(original, fixture.stored().single())
        assertEquals(0, fixture.confirmedCallbacks)
        assertEquals(0, fixture.adviceCallbacks)
        repository.recoverCorrection(binding, id, true).getOrThrow()
        assertTrue(fixture.stored().isEmpty())
        compose.waitUntil(10_000) { global?.uiState?.value?.correctionObservation?.corrections?.isEmpty() == true }
        compose.onNodeWithText(context.getString(R.string.sync_status_overview_caption_settled))
            .performScrollTo().assertIsDisplayed()
        assertEquals(0, fixture.network.calls.size)
    }

    @Test
    fun deliveredCorrectionWithFailedStreamRemainsRecoverableAfterRoomReopenWithoutDetail() = runBlocking {
        val firstGraph = fixture.reopen()
        val repository = firstGraph.expenseRepository
        val binding = requireNotNull(repository.observeCorrections().first().access).binding
        val originalFact = repository.fetchExpense(42).getOrThrow()
        repository.submitCorrection(binding, originalFact,
            ExpenseCorrectionDraft("全局核对已送达更正", originalAmountMinor = 1_200L)).getOrThrow()
        val original = fixture.stored().single()
        fixture.network.loseResponse = false
        fixture.network.failStreamReads = true
        assertEquals(1, fixture.drain().done)
        assertEquals(1, fixture.network.results.size)
        assertEquals(1_200L, fixture.network.current.amountCents)
        assertEquals(1_000L, repository.fetchExpenseFromLocalCache(42).getOrThrow().amountCents)
        assertEquals("done", fixture.stored().single()["status"])

        val graph = fixture.reopen()
        var opened: Long? = null
        compose.runOnIdle {
            global = outboxStatusViewModelFactory(fixture.outbox, graph.expenseRepository,
                OutboxRecoveryRepositories(graph.debtCreationRepository, graph.recurringRepository.occurrences,
                    graph.incomePlanRepository, graph.debtAdjustmentRepository)).create(OutboxStatusViewModel::class.java)
        }
        compose.setContent { TicketboxTheme(skin = AppSkin.Paper) {
            SyncStatusScreen(requireNotNull(global), {}, onOpenExpense = { opened = it }, onOpenInbox = {})
        } }
        compose.waitUntil(10_000) { global?.uiState?.value?.correctionObservation?.corrections?.singleOrNull()?.delivered == true }
        compose.onNodeWithText("更正已送达；部分事实尚待刷新。").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("原因：全局核对已送达更正").performScrollTo().assertIsDisplayed()
        compose.onNodeWithText("重试原提交").assertDoesNotExist()
        compose.onNodeWithText("刷新并核对当前事实").performScrollTo().performClick()
        assertEquals(42L, opened)
        assertEquals(1_200L, graph.expenseRepository.fetchExpenseFactBundle(42).getOrThrow().root.amountCents)
        assertTrue(requireNotNull(fixture.stored().single()["lastError"]).startsWith("correction_refresh_required:"))
        assertTrue(graph.expenseRepository.fetchExpense(42).isFailure)
        assertEquals("done", fixture.stored().single()["status"])
        compose.onNodeWithText("更正已送达；部分事实尚待刷新。").performScrollTo().assertIsDisplayed()

        fixture.network.failStreamReads = false
        assertEquals(1_200L, graph.expenseRepository.fetchExpense(42).getOrThrow().amountCents)
        compose.waitUntil(10_000) { compose.onAllNodes(hasText("原因：全局核对已送达更正")).fetchSemanticsNodes().isEmpty() }
        for (column in listOf("payload", "idempotencyKey", "expectedRowVersion", "ownerKey", "ledgerId")) {
            assertEquals(original[column], fixture.stored().single()[column])
        }
        assertEquals("done", fixture.stored().single()["status"])
        assertEquals(1, fixture.network.calls.size)
        assertEquals(1, fixture.network.results.size)
        assertEquals(0, fixture.drain().done)
    }

    private fun finishOriginalReplay(original: Map<String, String?>) {
        fixture.network.loseResponse = false
        fixture.failCachePublication = true
        val callbacksBefore = fixture.confirmedCallbacks
        assertEquals(1, runBlocking { fixture.drain() }.done)
        compose.waitUntil(10_000) { model.value?.uiState?.value?.corrections?.singleOrNull()?.delivered == true }
        assertEquals(callbacksBefore + 1, fixture.confirmedCallbacks)
        assertEquals(1, fixture.adviceCallbacks)
        assertEquals(fixture.network.calls.first(), fixture.network.calls.last())
        assertEquals(original["idempotencyKey"], fixture.network.calls.last().second)
        assertEquals(7L, fixture.network.calls.last().first.expectedRowVersion)
        assertEquals(1, fixture.network.results.size)
        assertEquals(1_000L, model.value?.uiState?.value?.expense?.amountCents)
        compose.onNodeWithText("更正已送达；部分事实尚待刷新。").performScrollTo().assertIsDisplayed()
        fixture.network.failReads = false
        fixture.failCachePublication = false
        compose.onNodeWithText("刷新并核对当前事实").performScrollTo().performClick()
        compose.waitUntil(10_000) { model.value?.uiState?.value?.expense?.amountCents == 1_200L &&
            model.value?.uiState?.value?.revisions?.singleOrNull()?.revisionNumber == 4L }
        compose.onNodeWithText("更正已送达，当前事实已刷新。").performScrollTo().assertIsDisplayed()
        assertEquals(2, fixture.network.calls.size)
    }

    private fun installModel() {
        val graph = fixture.reopen()
        compose.runOnIdle { model.value = ExpenseFactViewModel(42, graph.expenseRepository) }
    }
    private fun stopModel() = compose.runOnIdle { model.value?.viewModelScope?.cancel() }
}
