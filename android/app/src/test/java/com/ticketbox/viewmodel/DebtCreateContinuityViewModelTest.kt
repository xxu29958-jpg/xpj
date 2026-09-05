package com.ticketbox.viewmodel

import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
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
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtCreateContinuityViewModelTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun repeatedSaveWhileSubmittingEmitsOnlyOneCreate() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val repository = readyRepository(gate)
        val viewModel = DebtListViewModel(repository)
        advanceUntilIdle()
        fillDraft(viewModel)

        viewModel.submitDraft()
        runCurrent()
        assertTrue(viewModel.state.value.isSubmitting)
        viewModel.submitDraft()
        runCurrent()
        val commandsDuringSubmission = repository.createDrafts.toList()
        gate.complete(Unit)
        advanceUntilIdle()

        assertEquals(1, commandsDuringSubmission.size)
        assertEquals(12_345L, commandsDuringSubmission.single().principalAmountCents)
        assertEquals("出差垫付车费", commandsDuringSubmission.single().note)
    }

    @Test
    fun editsWhileSubmittingCannotReplaceTheVisibleSubmittedSnapshot() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val repository = readyRepository(gate)
        val viewModel = DebtListViewModel(repository)
        advanceUntilIdle()
        fillDraft(viewModel)

        viewModel.submitDraft()
        runCurrent()
        viewModel.updateDraftAmount("999.00")
        viewModel.updateDraftCounterparty("另一位")
        viewModel.updateDraftNote("另一笔用途")
        val visibleSnapshot = viewModel.state.value.addDraft
        gate.complete(Unit)
        advanceUntilIdle()

        assertEquals("123.45", visibleSnapshot.amountYuanInput)
        assertEquals("小王", visibleSnapshot.counterpartyLabel)
        assertEquals("出差垫付车费", visibleSnapshot.note)
        assertEquals(12_345L, repository.createDrafts.single().principalAmountCents)
    }

    private fun readyRepository(gate: CompletableDeferred<Unit>): FakeDebtActions =
        FakeDebtActions(listResult = Result.success(listOf(sampleDebt()))).apply {
            createGate = gate
        }

    private fun fillDraft(viewModel: DebtListViewModel) {
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("123.45")
        viewModel.updateDraftNote("出差垫付车费")
    }
}
