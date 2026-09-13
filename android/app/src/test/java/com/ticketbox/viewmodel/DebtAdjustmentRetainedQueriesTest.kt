package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.Goal
import java.lang.reflect.Proxy
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtAdjustmentRetainedQueriesTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun createGoalKeepsItsDraftWhileOnlyAPostTerminalCanonicalReadCanRestoreSave() = runTest(dispatcher) {
        for (terminal in listOf(PendingMutationStatus.Abandoned, PendingMutationStatus.Done)) {
            val original = sampleDebt().copy(rowVersion = 7)
            val debts = FakeDebtActions(listResult = Result.success(listOf(original)))
            val calls = mutableListOf<Pair<String, List<String>>>()
            val vm = CreateDebtGoalViewModel(retainedCreateReports(calls), debts, debts.writes)
            try {
                advanceUntilIdle()
                vm.updateName("保留原计划")
                vm.toggleDebt(original.publicId)
                assertTrue(vm.state.value.canSubmit)
                val oldRead = CompletableDeferred<Unit>()
                debts.listGate = oldRead
                vm.refreshCandidates()
                runCurrent()
                debts.writes.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.Failed))
                runCurrent()
                assertTrue(vm.state.value.candidates.isEmpty())
                assertFalse(vm.state.value.canSubmit)
                debts.listGate = null
                debts.listResult = Result.failure(IllegalStateException("post-terminal read unavailable"))
                debts.writes.rows.value = listOf(pendingAdjustment(status = terminal))
                advanceUntilIdle()
                assertNotNull(vm.state.value.loadError)
                oldRead.complete(Unit)
                advanceUntilIdle()
                assertNotNull(vm.state.value.loadError, "The pre-terminal GET cannot clear the newer failure")
                assertEquals("保留原计划", vm.state.value.name)
                assertEquals(setOf(original.publicId), vm.state.value.selectedDebtIds)
                vm.submit()
                advanceUntilIdle()
                assertTrue(calls.isEmpty())
                debts.listResult = Result.success(listOf(original))
                vm.refreshCandidates()
                advanceUntilIdle()
                assertEquals(terminal == PendingMutationStatus.Abandoned, vm.state.value.canSubmit)
                if (terminal == PendingMutationStatus.Done) {
                    assertNotNull(vm.state.value.loadError)
                    debts.listResult = Result.success(listOf(original.copy(rowVersion = 8)))
                    vm.refreshCandidates()
                    advanceUntilIdle()
                }
                assertNull(vm.state.value.loadError)
                assertTrue(vm.state.value.canSubmit)
                vm.submit()
                advanceUntilIdle()
                assertEquals(listOf("保留原计划" to listOf(original.publicId)), calls)
            } finally {
                vm.viewModelScope.coroutineContext.job.cancelAndJoin()
            }
        }
    }

    @Test
    fun debtListKeepsDraftAndRejectsOldReadsAfterEitherTerminal() = runTest(dispatcher) {
        val original = sampleDebt().copy(rowVersion = 7)
        val debts = FakeDebtActions(listResult = Result.success(listOf(original)))
        val vm = DebtListViewModel(debts, debts.creation, debts.writes)
        try {
            advanceUntilIdle()
            vm.updateDraftField(DebtDraftField.Counterparty, "未提交的新欠款")
            val initialReads = debts.listCalls
            debts.writes.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.Failed))
            advanceUntilIdle()
            assertEquals(initialReads, debts.listCalls, "Unresolved emissions do not replay canonical queries")
            debts.writes.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.Abandoned))
            advanceUntilIdle()
            assertEquals(initialReads + 1, debts.listCalls)
            assertEquals(listOf(original), vm.state.value.debts)
            assertNull(vm.state.value.error)
            val oldRead = CompletableDeferred<Unit>()
            debts.listGate = oldRead
            vm.refresh()
            runCurrent()
            debts.listGate = null
            debts.writes.rows.value += pendingAdjustment(id = 2, status = PendingMutationStatus.Done)
            advanceUntilIdle()
            assertNotNull(vm.state.value.error, "Done cannot accept the original OCC as its confirmed result")
            oldRead.complete(Unit)
            advanceUntilIdle()
            assertNotNull(vm.state.value.error)
            assertEquals("未提交的新欠款", vm.state.value.addDraft.counterpartyLabel)
            debts.listResult = Result.success(listOf(original.copy(rowVersion = 8)))
            vm.refresh()
            advanceUntilIdle()
            assertNull(vm.state.value.error)
            assertEquals(8L, vm.state.value.debts.single().rowVersion)
            assertEquals("未提交的新欠款", vm.state.value.addDraft.counterpartyLabel)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }
}

private fun retainedCreateReports(calls: MutableList<Pair<String, List<String>>>): ReportsActions {
    val unused = Proxy.newProxyInstance(ReportsActions::class.java.classLoader,
        arrayOf(ReportsActions::class.java)) { _, method, _ -> error("Unexpected report call: ${method.name}") } as ReportsActions
    return object : ReportsActions by unused {
        override fun canModifyLedger() = true
        override suspend fun createDebtGoal(name: String, debtPublicIds: List<String>, expectedBinding: com.ticketbox.data.repository.LogicalSessionBinding): Result<Goal> {
            calls += name to debtPublicIds
            return Result.failure(IllegalStateException("Synthetic creation refusal after recording the exact request"))
        }
    }
}
