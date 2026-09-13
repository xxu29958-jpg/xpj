package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseCorrectionObservation
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.domain.model.IncomeSourceType
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class IncomePlanGlobalRecoveryViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setup() = Dispatchers.setMain(dispatcher)
    @AfterTest fun tearDown() = Dispatchers.resetMain()

    @Test fun completedIncomeWithoutReceiptStaysInGlobalReviewUntilExplicitLocalStop() = runTest(dispatcher) {
        val harness = outboxStatusHarness()
        val binding = requireNotNull(harness.expenseRepository.captureDeferredLedgerBinding())
        val id = harness.incomePlans.create(binding, IncomePlanDraft("2026-09", "JPY", "旧版收入",
            IncomeSourceType.SALARY, amountCents = 1200, payDay = 12)).getOrThrow()
        harness.outbox.markDone(id)
        val vm = harness.createGlobalViewModel()
        try {
            val ready = vm.uiState.first { it.bindingReady && it.incomeSubmissions[id]?.requiresReview == true }
            val original = requireNotNull(ready.incomeSubmissions[id]).row
            assertFalse(ready.offersRetry(original))
            vm.retry(original)
            vm.uiState.first { it.message != null && it.busyRowId == null }
            assertEquals(original, harness.incomePlans.observeSubmissions(binding).first().single().row)
            vm.dropFailed(original)
            vm.uiState.first { id !in it.incomeSubmissions && it.busyRowId == null }
            assertTrue(harness.incomePlans.observeSubmissions(binding).first().isEmpty())
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    @Test fun anIncomeOriginalWithoutItsOwnerDescriptionCannotUseGenericRetry() {
        val binding = LogicalSessionBinding("https://example.test", "owner", "owner", "session", "binding")
        for (type in incomePlanSubmissionTypes) {
            val row = OutboxRow(43, binding.serverUrl, binding.ledgerId, binding.ownerKey, type,
                "income_plan:17", "{}", 3, PendingMutationStatus.Failed, 1, "client_upgrade_required",
                "2026-09-09T00:00:00Z", null, null, "original-income-key")
            val state = OutboxStatusUiState(binding = binding, bindingReady = true,
                correctionObservation = ExpenseCorrectionObservation(LedgerAccessContext(binding, true), emptyList()))
            assertFalse(state.offersRetry(row))
        }
    }

    @Test fun createRecoveryUsesTheOriginalMonthCurrencyAndKeyAndRequiresWriteAccess() = runTest(dispatcher) {
        val harness = outboxStatusHarness()
        val binding = requireNotNull(harness.expenseRepository.captureDeferredLedgerBinding())
        val id = harness.incomePlans.create(binding, IncomePlanDraft("2026-09", "JPY", "原日元收入",
            IncomeSourceType.SALARY, amountCents = 1200, payDay = 12)).getOrThrow()
        harness.outbox.markFailed(id, "client_upgrade_required")
        val original = harness.outbox.observeStatus().first().failed.single()
        val vm = harness.createGlobalViewModel()
        try {
            val ready = vm.uiState.first { it.bindingReady && it.incomeSubmissions.containsKey(id) }
            val pending = requireNotNull(ready.incomeSubmissions[id])
            assertTrue(ready.offersRetry(original))
            assertEquals("JPY", pending.intent?.homeCurrencyCode)
            assertEquals("2026-09", pending.intent?.request?.intentMonth)
            assertEquals(1200L, pending.intent?.request?.amountCents)
            val access = requireNotNull(ready.correctionObservation.access)
            assertFalse(ready.copy(correctionObservation = ExpenseCorrectionObservation(access.copy(canModify = false), emptyList())).offersRetry(original))
            assertNull(harness.incomePlans.describeSubmission(original.copy(serverUrl = "https://foreign.test")))
            vm.retry(original.copy(ledgerId = "foreign"))
            vm.keepMine(original.copy(targetId = "expense:7"))
            runCurrent()
            assertEquals(original, harness.outbox.observeStatus().first().failed.single())
            assertNull(vm.uiState.value.message)
            vm.retry(original)
            val retried = harness.outbox.observeActiveByTypes(incomePlanSubmissionTypes)
                .first { it.singleOrNull()?.status == PendingMutationStatus.Pending }.single()
            assertEquals(original.payloadJson, retried.payloadJson)
            assertEquals(original.idempotencyKey, retried.idempotencyKey)
            assertEquals(original.expectedRowVersion, retried.expectedRowVersion)
            assertEquals(original.targetId, retried.targetId)
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    @Test fun anUnrecognizedOriginalRemainsReviewableAndOnlyItsLocalRetryCanBeStopped() = runTest(dispatcher) {
        val harness = outboxStatusHarness()
        val id = harness.outbox.enqueue(PendingMutationType.CreateIncomePlan, "income_plan_create:legacy",
            "{\"label\":\"unknown currency\",\"amount_cents\":1200}", 0, "legacy")
        harness.outbox.markFailed(id, "client_upgrade_required")
        val original = harness.outbox.observeStatus().first().failed.single()
        val vm = harness.createGlobalViewModel()
        try {
            val ready = vm.uiState.first { it.bindingReady && it.incomeSubmissions.containsKey(id) }
            assertFalse(ready.offersRetry(original))
            assertNull(ready.incomeSubmissions[id]?.intent)
            vm.retry(original)
            vm.uiState.first { it.message != null && it.busyRowId == null }
            assertEquals(original, harness.outbox.observeStatus().first().failed.single())
            vm.dropFailed(original)
            harness.outbox.observeStatus().first { it.failed.isEmpty() }
            assertTrue(harness.outbox.observeActiveByTypes(incomePlanSubmissionTypes, includeCompleted = true).first().isEmpty())
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    @Test fun legacyVersionOneEditReplaysItsOriginalBytesButUnverifiedReceiptCannotLoopRetry() = runTest(dispatcher) {
        val harness = outboxStatusHarness()
        val binding = requireNotNull(harness.expenseRepository.captureDeferredLedgerBinding())
        val payload = """{"revision":1,"planPublicId":"income-17","originalLabel":"原工资","originalAmountCents":1000,"homeCurrencyCode":"JPY","originSessionGeneration":"${binding.sessionGeneration}","originBindingRevision":"${binding.bindingRevision}","request":{"intent_month":"2026-09","expected_row_version":0,"amount_cents":1200}}"""
        val id = harness.outbox.enqueue(PendingMutationType.UpdateIncomePlan, "income_plan:income-17", payload, 3, "original-edit-key")
        harness.outbox.markFailed(id, "runtime_version_mismatch")
        val original = harness.outbox.observeStatus().first().failed.single()
        val vm = harness.createGlobalViewModel()
        try {
            vm.uiState.first { it.bindingReady && it.incomeSubmissions[id]?.canRetry == true }
            vm.retry(original)
            val retried = harness.outbox.observeActiveByTypes(incomePlanSubmissionTypes)
                .first { it.singleOrNull()?.status == PendingMutationStatus.Pending }.single()
            assertEquals(payload, retried.payloadJson)
            assertEquals("original-edit-key", retried.idempotencyKey)
            assertEquals(3L, retried.expectedRowVersion)
            harness.outbox.markFailed(id, "返回的收入计划与原提交不一致，已保留记录，请核对。")
            val blocked = vm.uiState.first { it.incomeSubmissions[id]?.row?.lastError == "返回的收入计划与原提交不一致，已保留记录，请核对。" }
            val uncertain = requireNotNull(blocked.incomeSubmissions[id]).row
            assertFalse(blocked.offersRetry(uncertain))
            vm.uiState.first { it.busyRowId == null }
            vm.retry(uncertain)
            vm.uiState.first { it.message != null && it.busyRowId == null }
            assertEquals(uncertain, harness.outbox.observeStatus().first().failed.single())
        } finally { vm.viewModelScope.coroutineContext.job.cancelAndJoin() }
    }

    private fun OutboxStatusHarness.createGlobalViewModel() = OutboxStatusViewModel(outbox, expenseRepository,
        OutboxRecoveryRepositories(debtCreation, null, incomePlans, debtWrites, goalEdits, budgetSaves, recurringItems, rules))
}
