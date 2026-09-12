package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtTask
import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
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

class MemberSettlementDetailResultTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun acknowledgedFoldReachesParentAndSurvivesBothOldAndFailedReads() = runTest(dispatcher) {
        val old = sampleMemberDebt().copy(rowVersion = 2, status = "open", remainingAmountCents = 20000, paidAmountCents = 0)
        val repository = AdjustmentDetailActions().apply { getResult = Result.success(old) }
        val model = DebtDetailViewModel(repository, FakeDebtWriteActions())
        model.loadDebt("d1")
        advanceUntilIdle()
        val task = DebtTask(requireNotNull(model.state.value.binding), "d1")
        val gate = CompletableDeferred<Unit>()
        repository.getGate = gate
        model.refresh()
        runCurrent()
        val accepted = old.copy(rowVersion = 3, remainingAmountCents = 12500, paidAmountCents = 7500)
        model.applyMemberResult(task, accepted)
        assertEquals(accepted, model.state.value.debt)
        assertFalse(model.state.value.isLoading)
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(accepted, model.state.value.debt)

        repository.getGate = null
        repository.getResult = Result.failure(RepositoryException("refresh unavailable"))
        model.refresh()
        advanceUntilIdle()
        assertEquals(accepted, model.state.value.debt)
        assertNotNull(model.state.value.error)
    }

    @Test
    fun staleResultCannotReplaceNewerFoldAnotherDebtOrBinding() = runTest(dispatcher) {
        val current = sampleMemberDebt()
        val repository = AdjustmentDetailActions().apply { getResult = Result.success(current) }
        val writes = FakeDebtWriteActions()
        val model = DebtDetailViewModel(repository, writes)
        model.loadDebt("d1")
        advanceUntilIdle()
        val task = DebtTask(requireNotNull(model.state.value.binding), "d1")
        model.applyMemberResult(task, current.copy(rowVersion = 1))
        model.applyMemberResult(task.copy(debtPublicId = "d2"), current.copy(publicId = "d2"))
        model.applyMemberResult(task.copy(binding = task.binding.copy(bindingRevision = "old")), current.copy(rowVersion = 8))
        assertEquals(current, model.state.value.debt)
        writes.access.value = requireNotNull(writes.access.value).copy(binding = task.binding.copy(ownerKey = "replacement"))
        model.applyMemberResult(task, current.copy(rowVersion = 8))
        advanceUntilIdle()
        assertNull(model.state.value.debt)
    }
}
