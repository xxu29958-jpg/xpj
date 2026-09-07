package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CurrencyCode
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
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class MemberRepaymentProposalCommandContinuityTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setUp() { Dispatchers.setMain(dispatcher) }

    @AfterTest
    fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun repeatedSubmitKeepsOneActiveProposalCommand() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val repository = ProposalTestActions().apply { proposeGate = gate }
        val viewModel = MemberRepaymentProposalViewModel(repository)
        viewModel.load("d1")
        advanceUntilIdle()
        viewModel.openForm(ProposalForm.Propose)
        viewModel.updateAmount("200.00")
        viewModel.submit(expectedRowVersion = 1, currency = CurrencyCode.CNY)
        viewModel.submit(expectedRowVersion = 1, currency = CurrencyCode.CNY)
        runCurrent()
        val callsWhilePending = repository.proposeCalls.size
        gate.complete(Unit)
        advanceUntilIdle()

        assertEquals(1, callsWhilePending)
    }

    @Test
    fun previousDebtCompletionCannotClearTheNewDebtForm() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val repository = ProposalTestActions().apply { proposeGate = gate }
        val viewModel = MemberRepaymentProposalViewModel(repository)
        viewModel.load("d1")
        advanceUntilIdle()
        viewModel.openForm(ProposalForm.Propose)
        viewModel.updateAmount("200.00")
        viewModel.submit(expectedRowVersion = 1, currency = CurrencyCode.CNY)
        runCurrent()

        viewModel.load("d2")
        advanceUntilIdle()
        viewModel.openForm(ProposalForm.Propose)
        viewModel.updateAmount("75.50")
        viewModel.updateNote("New debt draft")
        gate.complete(Unit)
        advanceUntilIdle()

        assertEquals(ProposalForm.Propose, viewModel.state.value.activeForm)
        assertEquals("75.50", viewModel.state.value.amountInput)
        assertEquals("New debt draft", viewModel.state.value.noteInput)
        assertNull(viewModel.state.value.flashMessage)
    }

    @Test
    fun acknowledgedProposalRemainsVisibleWhenFollowingRefreshFails() = runTest(dispatcher) {
        val repository = ProposalTestActions()
        val viewModel = MemberRepaymentProposalViewModel(repository)
        viewModel.load("d1")
        advanceUntilIdle()
        repository.listResult = Result.failure(RepositoryException("list unavailable"))
        viewModel.openForm(ProposalForm.Propose)
        viewModel.updateAmount("200.00")
        viewModel.submit(expectedRowVersion = 1, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        assertEquals(repository.proposalResult.getOrThrow(), viewModel.state.value.pendingProposal)
        assertNull(viewModel.state.value.activeForm)
        assertNotNull(viewModel.state.value.flashMessage)
    }
}
