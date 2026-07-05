package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseRepository
import com.ticketbox.data.repository.FakeApiService
import com.ticketbox.data.repository.FakeApiServiceFactory
import com.ticketbox.data.repository.FakeExpenseDao
import com.ticketbox.data.repository.FakePendingMutationDao
import com.ticketbox.data.repository.FakeSessionTokenStore
import com.ticketbox.data.repository.OutboxRepository
import com.ticketbox.data.repository.OutboxRow
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
        val vm = OutboxStatusViewModel(harness.outbox, harness.expenseRepository)
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
        val vm = OutboxStatusViewModel(harness.outbox, harness.expenseRepository)
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

    private fun harness(): Harness {
        val tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") }
        val api = FakeApiServiceFactory(FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0))
        val expenseRepository = ExpenseRepository(
            expenseDao = FakeExpenseDao(),
            apiClient = api,
            settingsStore = boundSettingsStore(),
            tokenStore = tokenStore,
        )
        return Harness(
            outbox = OutboxRepository(dao = FakePendingMutationDao()),
            expenseRepository = expenseRepository,
        )
    }

    private data class Harness(
        val outbox: OutboxRepository,
        val expenseRepository: ExpenseRepository,
    )
}
