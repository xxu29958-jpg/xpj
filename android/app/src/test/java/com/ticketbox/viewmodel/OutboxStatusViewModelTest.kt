package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.DebtCreationRepository
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
    fun keepMineWithoutServerRowShowsDangerTone() = runTest(dispatcher) {
        val harness = harness()
        val row = harness.conflictRow(targetId = "expense:local:client-1")
        val vm = OutboxStatusViewModel(harness.outbox, harness.expenseRepository, harness.debtCreation, incomePlans = harness.incomePlans)
        runCurrent()

        vm.keepMine(row)
        runCurrent()

        assertEquals(UiText.res(R.string.sync_status_vm_keep_mine_unavailable), vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        assertNull(vm.uiState.value.busyRowId)
    }

    @Test
    fun resolvingRowClearsStaleDangerTone() = runTest(dispatcher) {
        val harness = harness()
        val row = harness.conflictRow(targetId = "expense:local:client-1")
        val vm = OutboxStatusViewModel(harness.outbox, harness.expenseRepository, harness.debtCreation, incomePlans = harness.incomePlans)
        runCurrent()

        vm.keepMine(row)
        runCurrent()
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)

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
            harness.debtCreation, incomePlans = harness.incomePlans).create(OutboxStatusViewModel::class.java)
        runCurrent()
        kotlin.test.assertNotNull(vm.uiState.value.incomeEdits[id])
        vm.retry(row)
        runCurrent()
        assertEquals(row, harness.outbox.observeStatus().first().failed.single())
        assertEquals(UiText.res(R.string.income_plan_edit_unsupported), vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
    }

    private fun harness(): Harness {
        val tokenStore = TestSessionFixture().apply { saveToken("session-token") }
        val api = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0))
        val expenseRepository = ExpenseRepository(
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
        )
    }

    private data class Harness(
        val outbox: OutboxRepository,
        val expenseRepository: ExpenseRepository,
        val debtCreation: DebtCreationRepository,
        val incomePlans: IncomePlanRepository,
    )
}
