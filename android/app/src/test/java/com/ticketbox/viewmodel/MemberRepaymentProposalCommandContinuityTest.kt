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
        viewModel.load(memberDebtTask("d1"))
        advanceUntilIdle()
        viewModel.openForm(requireNotNull(viewModel.state.value.task), ProposalForm.Propose)
        viewModel.updateAmount(requireNotNull(viewModel.state.value.task), "200.00")
        viewModel.submit(requireNotNull(viewModel.state.value.task), expectedRowVersion = 1, currency = CurrencyCode.CNY)
        viewModel.submit(requireNotNull(viewModel.state.value.task), expectedRowVersion = 1, currency = CurrencyCode.CNY)
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
        viewModel.load(memberDebtTask("d1"))
        advanceUntilIdle()
        viewModel.openForm(requireNotNull(viewModel.state.value.task), ProposalForm.Propose)
        viewModel.updateAmount(requireNotNull(viewModel.state.value.task), "200.00")
        viewModel.submit(requireNotNull(viewModel.state.value.task), expectedRowVersion = 1, currency = CurrencyCode.CNY)
        runCurrent()

        viewModel.load(memberDebtTask("d2"))
        advanceUntilIdle()
        viewModel.openForm(requireNotNull(viewModel.state.value.task), ProposalForm.Propose)
        viewModel.updateAmount(requireNotNull(viewModel.state.value.task), "75.50")
        viewModel.updateNote(requireNotNull(viewModel.state.value.task), "New debt draft")
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
        viewModel.load(memberDebtTask("d1"))
        advanceUntilIdle()
        repository.listResult = Result.failure(RepositoryException("list unavailable"))
        viewModel.openForm(requireNotNull(viewModel.state.value.task), ProposalForm.Propose)
        viewModel.updateAmount(requireNotNull(viewModel.state.value.task), "200.00")
        viewModel.submit(requireNotNull(viewModel.state.value.task), expectedRowVersion = 1, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        assertEquals(repository.proposalResult.getOrThrow(), viewModel.state.value.pendingProposal)
        assertNull(viewModel.state.value.activeForm)
        assertNotNull(viewModel.state.value.flashMessage)
    }
}
