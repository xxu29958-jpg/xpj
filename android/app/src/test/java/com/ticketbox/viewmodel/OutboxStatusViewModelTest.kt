package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.DebtCreationRepository
import com.ticketbox.data.repository.DebtAdjustmentRepository
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakeApiServiceFactory
import com.ticketbox.data.repository.FakeExpenseDao
import com.ticketbox.data.repository.FakePendingMutationDao
import com.ticketbox.data.repository.TestSessionFixture
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.IncomePlanRepository
import com.ticketbox.data.repository.testOutboxRepository
import com.ticketbox.data.repository.testApiServiceProvider
import com.ticketbox.data.repository.testServerSessionBinding
import com.ticketbox.data.repository.boundSettingsStore
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.job
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class OutboxStatusViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setup() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun originalOffsetCannotBeRebasedByGlobalKeepMine() = runTest(dispatcher) {
        val harness = harness()
        val id = harness.outbox.enqueue(PendingMutationType.CreateExpenseOffset, "expense:7",
            "{\"kind\":\"refund\",\"original_amount_minor\":1000,\"accounting_date\":\"2026-09-03\",\"reason\":\"Original refund\",\"expected_row_version\":7}",
            7, "original-refund-key")
        harness.outbox.markConflict(id, "state_conflict")
        val original = harness.outbox.observeStatus().first().conflicts.single()
        val vm = outboxStatusViewModelFactory(harness.outbox, harness.expenseRepository,
            OutboxRecoveryRepositories(harness.debtCreation, null, harness.incomePlans, harness.debtAdjustments, harness.goalEdits))
            .create(OutboxStatusViewModel::class.java)
        try {
            runCurrent()
            vm.keepMine(original)
            runCurrent()
            assertEquals(original, harness.outbox.observeStatus().first().conflicts.single())
            assertEquals(UiText.res(R.string.expense_offset_original_requires_review), vm.uiState.value.message)
            assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
            assertNull(vm.uiState.value.busyRowId)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun rejectedKeepMineShowsFeedbackAndDropClearsIt() = runTest(dispatcher) {
        val harness = harness()
        val row = harness.conflictRow(targetId = "expense:local:client-1")
        val vm = OutboxStatusViewModel(harness.outbox, harness.expenseRepository,
            OutboxRecoveryRepositories(harness.debtCreation, null, harness.incomePlans, harness.debtAdjustments, harness.goalEdits))
        runCurrent()

        vm.keepMine(row)
        runCurrent()
        assertEquals(UiText.res(R.string.sync_status_vm_keep_mine_unavailable), vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        assertNull(vm.uiState.value.busyRowId)

        vm.dropMine(row)
        runCurrent()

        assertNull(vm.uiState.value.message)
        assertEquals(MessageTone.Neutral, vm.uiState.value.messageTone)
    }

    private suspend fun Harness.conflictRow(targetId: String): OutboxRow {
        val rowId = outbox.enqueue(
            type = PendingMutationType.PatchExpense,
            targetId = targetId,
            payloadJson = "{}",
            expectedRowVersion = 1L,
        )
        outbox.markConflict(rowId, "state conflict")
        return outbox.observeStatus().first { it.conflicts.isNotEmpty() }.conflicts.single()
    }

    @Test
    fun unsupportedIncomeRetryKeepsTheOriginalFailedRecord() = runTest(dispatcher) {
        val harness = harness()
        val id = harness.outbox.enqueue(type = PendingMutationType.UpdateIncomePlan,
            targetId = "income_plan:old", payloadJson = "{\"amount_cents\":120000}", expectedRowVersion = 1L)
        harness.outbox.markFailed(id, "unsupported original intent")
        val row = harness.outbox.observeStatus().first().failed.single()
        val vm = outboxStatusViewModelFactory(harness.outbox, harness.expenseRepository,
            OutboxRecoveryRepositories(harness.debtCreation, null, harness.incomePlans, harness.debtAdjustments, harness.goalEdits))
            .create(OutboxStatusViewModel::class.java)
        runCurrent()
        kotlin.test.assertNotNull(vm.uiState.value.incomeEdits[id])
        vm.retry(row)
        runCurrent()
        assertEquals(row, harness.outbox.observeStatus().first().failed.single())
        assertEquals(UiText.res(R.string.income_plan_edit_unsupported), vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
    }

    @Test
    fun unretryableAdjustmentsKeepOriginalFailedRecordsAndAllowExplicitDrop() = runTest(dispatcher) {
        for (supported in listOf(false, true)) {
            val harness = harness()
            val id = if (supported) {
                val binding = assertNotNull(harness.debtAdjustments.currentAccess()).binding
                harness.debtAdjustments.save(binding, sampleDebt().copy(rowVersion = 7), -5_000, "减免").getOrThrow()
            } else harness.outbox.enqueue(
                type = PendingMutationType.RecordDebtAdjustment, targetId = "debt:debt-1",
                payloadJson = "{\"revision\":99}", expectedRowVersion = 7,
                idempotencyKey = "original-unsupported-adjustment",
            )
            harness.outbox.markFailed(id, if (supported) "debt_adjustment_negative_remaining" else "unsupported original intent")
            val original = harness.outbox.observeStatus().first().failed.single()
            val vm = outboxStatusViewModelFactory(harness.outbox, harness.expenseRepository,
                OutboxRecoveryRepositories(harness.debtCreation, null, harness.incomePlans, harness.debtAdjustments, harness.goalEdits))
                .create(OutboxStatusViewModel::class.java)
            runCurrent()
            val described = assertNotNull(vm.uiState.value.debtAdjustments[id])
            assertEquals(original, described.row)
            assertEquals(supported, described.hasSupportedIntent)
            assertEquals(false, described.canRetry)
            if (supported) {
                assertEquals(-5_000L, described.intent?.request?.amountCents)
                assertEquals("减免", described.intent?.request?.reason)
            }

            vm.retry(original)
            runCurrent()

            assertEquals(original, harness.outbox.observeStatus().first().failed.single())
            assertEquals(0, harness.outbox.observeStatus().first().queueDepth)
            assertEquals(UiText.res(if (supported) R.string.debt_adjustment_reduction_rejected
                else R.string.debt_adjustment_unsupported), vm.uiState.value.message)
            assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)

            val priorJobs = vm.viewModelScope.coroutineContext.job.children.toSet()
            vm.dropFailed(original)
            val dropJob = vm.viewModelScope.coroutineContext.job.children.single { it !in priorJobs }
            dropJob.join()
            runCurrent()
            assertNull(vm.uiState.value.busyRowId)
            assertNull(vm.uiState.value.message)
            assertEquals(emptyList(), harness.outbox.observeStatus().first().failed)
            val stopped = assertNotNull(vm.uiState.value.debtAdjustments[id])
            assertEquals(PendingMutationStatus.Abandoned, stopped.row.status)
            assertEquals(original.payloadJson, stopped.row.payloadJson)
            assertEquals(original.idempotencyKey, stopped.row.idempotencyKey)
            assertEquals(original.expectedRowVersion, stopped.row.expectedRowVersion)
            assertEquals(false, stopped.canRetry)
        }
    }

    @Test
    fun reopenedSyncStatusKeepsOriginalAdjustmentContextWhilePendingThenInFlight() = runTest(dispatcher) {
        val harness = harness()
        val binding = assertNotNull(harness.debtAdjustments.currentAccess()).binding
        val debt = sampleDebt().copy(rowVersion = 7)
        val id = harness.debtAdjustments.save(binding, debt, -5_000, "减免").getOrThrow()
        val types = setOf(PendingMutationType.RecordDebtAdjustment)
        val original = harness.outbox.observeActiveByTypes(types).first().single()

        // Open the global entry after persistence; no canonical Debt read or retry is needed.
        val vm = outboxStatusViewModelFactory(harness.outbox, harness.expenseRepository,
            OutboxRecoveryRepositories(harness.debtCreation, null, harness.incomePlans, harness.debtAdjustments, harness.goalEdits))
            .create(OutboxStatusViewModel::class.java)
        runCurrent()

        val pending = vm.uiState.value.waitingDebtAdjustments.single()
        assertEquals(original, pending.row)
        assertEquals(id, pending.row.id)
        assertEquals(PendingMutationStatus.Pending, pending.row.status)
        assertEquals(0, pending.row.retryCount)
        assertNotNull(pending.row.idempotencyKey)
        val intent = assertNotNull(pending.intent)
        assertEquals(debt.publicId, intent.subject.publicId)
        assertEquals(debt.counterpartyLabel, intent.subject.label)
        assertEquals(debt.homeCurrencyCode, intent.subject.homeCurrencyCode)
        assertEquals(-5_000L, intent.request.amountCents)
        assertEquals("减免", intent.request.reason)
        assertEquals(7L, intent.request.expectedRowVersion)
        assertEquals(binding.sessionGeneration, intent.originSessionGeneration)
        assertEquals(binding.bindingRevision, intent.originBindingRevision)
        assertTrue(vm.uiState.value.status.failed.isEmpty())
        assertTrue(vm.uiState.value.status.conflicts.isEmpty())

        assertTrue(harness.outbox.tryClaim(id))
        runCurrent()

        val inFlight = vm.uiState.value.waitingDebtAdjustments.single()
        assertEquals(intent, inFlight.intent)
        assertNotNull(inFlight.row.attemptedAt)
        // retryCount counts claimed attempts: the first Pending-to-InFlight claim is 1.
        assertEquals(original.copy(status = PendingMutationStatus.InFlight, retryCount = 1,
            attemptedAt = inFlight.row.attemptedAt), inFlight.row)
        assertEquals(inFlight.row, harness.outbox.observeActiveByTypes(types).first().single())
        assertEquals(1, inFlight.row.retryCount)
        assertTrue(vm.uiState.value.status.failed.isEmpty())
        assertTrue(vm.uiState.value.status.conflicts.isEmpty())
        assertNull(vm.uiState.value.busyRowId)
    }

    @Test
    fun uploadRecoveryCannotUseTheGenericRetryOrFreshTokenExit() = runTest(dispatcher) {
        val harness = harness()
        val id = harness.outbox.enqueue(PendingMutationType.UploadScreenshot, "upload_batch:original", "original-payload",
            0, "original-key")
        harness.outbox.markFailed(id, "upload_intent_unsupported")
        val original = harness.outbox.observeStatus().first().failed.single()
        val vm = OutboxStatusViewModel(harness.outbox, harness.expenseRepository,
            OutboxRecoveryRepositories(harness.debtCreation, null, harness.incomePlans, harness.debtAdjustments, harness.goalEdits))
        runCurrent()

        vm.retry(original)
        runCurrent()
        assertEquals(original, harness.outbox.observeStatus().first().failed.single())
        assertEquals(UiText.res(R.string.sync_status_upload_recovery_body), vm.uiState.value.message)
        vm.dropFailed(original)
        runCurrent()
        assertEquals(original, harness.outbox.observeStatus().first().failed.single())
        harness.outbox.markConflict(id, "original-requires-review")
        val conflict = harness.outbox.observeStatus().first().conflicts.single()
        vm.keepMine(conflict)
        vm.dropMine(conflict)
        runCurrent()
        assertEquals(conflict, harness.outbox.observeStatus().first().conflicts.single())
        assertNull(vm.uiState.value.busyRowId)
    }

    @Test
    fun terminalGoalRefusalCannotBeRequeuedFromTheGlobalRecoveryEntrance() = runTest(dispatcher) {
        val harness = harness()
        val id = harness.outbox.enqueue(PendingMutationType.UpdateGoal, "goal:original",
            "{\"expected_row_version\":0,\"target_amount_cents\":1200}", 1, "original-goal-key")
        harness.outbox.markFailed(id, "目标参数已失效")
        val original = harness.outbox.observeStatus().first().failed.single()
        val vm = outboxStatusViewModelFactory(harness.outbox, harness.expenseRepository,
            OutboxRecoveryRepositories(harness.debtCreation, null, harness.incomePlans, harness.debtAdjustments, harness.goalEdits))
            .create(OutboxStatusViewModel::class.java)
        try {
            runCurrent()
            kotlin.test.assertFalse(vm.uiState.value.offersRetry(original))
            vm.retry(original)
            runCurrent()
            assertEquals(listOf(original), harness.outbox.observeStatus().first().failed)
            vm.dropFailed(original)
            runCurrent()
            assertTrue(harness.outbox.observeStatus().first().failed.isEmpty())
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    private fun harness(): Harness {
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val api = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0))
        val expenseRepository = com.ticketbox.data.repository.expenseRepositoryFixture(
            expenseDao = FakeExpenseDao(),
            binding = testServerSessionBinding(
                apiClient = api,
                settingsStore = boundSettingsStore(),
                tokenStore = tokenStore,
            ),
        )
        val outbox = testOutboxRepository(dao = FakePendingMutationDao())
        return Harness(
            outbox = outbox,
            expenseRepository = expenseRepository,
            debtCreation = DebtCreationRepository(
                testApiServiceProvider(api, tokenStore), outbox, OutboxAdapterGraph().debtCreateAdapter,
            ),
            incomePlans = IncomePlanRepository(testApiServiceProvider(api, tokenStore), outbox,
                OutboxAdapterGraph().incomePlanUpdateAdapter),
            debtAdjustments = DebtAdjustmentRepository(testApiServiceProvider(api, tokenStore), outbox,
                OutboxAdapterGraph().debtAdjustmentAdapter),
            goalEdits = com.ticketbox.data.repository.GoalEditRepository(testApiServiceProvider(api, tokenStore), outbox,
                OutboxAdapterGraph().goalUpdateAdapter, OutboxAdapterGraph().goalReceiptAdapter),
        )
    }

    private data class Harness(
        val outbox: OutboxRepository,
        val expenseRepository: ExpenseRepository,
        val debtCreation: DebtCreationRepository,
        val incomePlans: IncomePlanRepository,
        val debtAdjustments: DebtAdjustmentRepository,
        val goalEdits: com.ticketbox.data.repository.GoalEditRepository,
    )
}
