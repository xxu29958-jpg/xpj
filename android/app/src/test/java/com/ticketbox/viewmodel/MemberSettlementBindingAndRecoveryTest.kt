package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.DebtTask
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
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

class MemberSettlementBindingAndRecoveryTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun responseLossRetryKeepsTheOriginalKeyAndEditedIntentGetsAnother() = runTest(dispatcher) {
        val repository = ProposalTestActions(proposalResult = Result.failure(RepositoryException("response lost")))
        val model = MemberRepaymentProposalViewModel(repository)
        val task = memberDebtTask("d1")
        model.load(task)
        advanceUntilIdle()
        model.openForm(task, ProposalForm.Propose)
        model.updateAmount(task, "20.00")
        model.updateNote(task, "original note")
        repeat(2) {
            model.submit(task, 1, CurrencyCode.CNY)
            advanceUntilIdle()
        }
        assertEquals(2, repository.commandKeys.size)
        assertEquals(repository.commandKeys[0], repository.commandKeys[1])
        assertEquals("20.00", model.state.value.amountInput)
        assertNull(model.state.value.flashMessage)
        assertEquals(ProposalForm.Propose, model.state.value.activeForm)

        model.updateAmount(task, "25.00")
        model.submit(task, 1, CurrencyCode.CNY)
        advanceUntilIdle()
        assertNotEquals(repository.commandKeys[1], repository.commandKeys[2])
        assertEquals(listOf(2000L, 2000L, 2500L), repository.proposeCalls.map { it.proposedAmountCents })
    }

    @Test
    fun everyBindingReplacementRejectsRenderedCallbacksBeforeObserverDelivery() = runTest(dispatcher) {
        val task = memberDebtTask("d1")
        val binding = task.binding
        val replacements = listOf(binding.copy(serverUrl = "https://another.example"),
            binding.copy(ledgerId = "another"), binding.copy(ownerKey = "another-owner"),
            binding.copy(sessionGeneration = "another-session"), binding.copy(bindingRevision = "another-revision"))
        for (replacement in replacements) {
            val repository = ProposalTestActions()
            val model = MemberRepaymentProposalViewModel(repository)
            model.load(task)
            advanceUntilIdle()
            model.openForm(task, ProposalForm.Propose)
            model.updateAmount(task, "20.00")
            repository.access.value = LedgerAccessContext(replacement, true)
            model.submit(task, 1, CurrencyCode.CNY)
            model.withdraw(task, "p1")
            model.reject(task, "p1")
            model.forgive(task, 1)
            advanceUntilIdle()
            assertTrue(repository.commandKeys.isEmpty())
            assertNull(model.state.value.task)
            val nextTask = DebtTask(replacement, "d1")
            model.load(nextTask)
            model.openForm(nextTask, ProposalForm.Propose)
            model.updateAmount(nextTask, "75.50")
            model.updateAmount(task, "200.00")
            model.dismissForm(task)
            assertEquals("75.50", model.state.value.amountInput)
            assertEquals(ProposalForm.Propose, model.state.value.activeForm)
        }
    }

    @Test
    fun roleRevocationKeepsDraftButStopsWritesImmediately() = runTest(dispatcher) {
        val repository = ProposalTestActions()
        val model = MemberRepaymentProposalViewModel(repository)
        val task = memberDebtTask("d1")
        model.load(task)
        advanceUntilIdle()
        model.openForm(task, ProposalForm.Propose)
        model.updateAmount(task, "20.00")
        repository.access.value = LedgerAccessContext(task.binding, false)
        model.submit(task, 1, CurrencyCode.CNY)
        model.withdraw(task, "p1")
        model.reject(task, "p1")
        model.forgive(task, 1)
        advanceUntilIdle()
        assertTrue(repository.commandKeys.isEmpty())
        assertEquals("20.00", model.state.value.amountInput)
        assertFalse(model.state.value.canModify)
    }

    @Test
    fun nonCooperativeOldCompletionCannotOverwriteReplacementTask() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val repository = ProposalTestActions().apply { proposeGate = gate; nonCooperative = true }
        val model = MemberRepaymentProposalViewModel(repository)
        val original = memberDebtTask("d1")
        model.load(original)
        advanceUntilIdle()
        model.openForm(original, ProposalForm.Propose)
        model.updateAmount(original, "20.00")
        model.submit(original, 1, CurrencyCode.CNY)
        runCurrent()
        val replacement = memberDebtTask("d2")
        model.load(replacement)
        model.openForm(replacement, ProposalForm.Propose)
        model.updateAmount(replacement, "75.50")
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(replacement, model.state.value.task)
        assertEquals("75.50", model.state.value.amountInput)
        assertTrue(model.state.value.proposals.isEmpty())
        assertNull(model.state.value.flashMessage)
    }

    @Test
    fun reentryReconcilesCanonicalProposalWithoutClearingTheCurrentDraft() = runTest(dispatcher) {
        val repository = ProposalTestActions()
        val model = MemberRepaymentProposalViewModel(repository)
        val task = memberDebtTask("d1")
        model.load(task)
        advanceUntilIdle()
        model.openForm(task, ProposalForm.Propose)
        model.updateAmount(task, "20.00")
        repository.listResult = Result.success(listOf(sampleMemberProposal()))
        model.load(task)
        advanceUntilIdle()
        assertEquals("p1", model.state.value.pendingProposal?.publicId)
        assertEquals("20.00", model.state.value.amountInput)
        assertTrue(repository.commandKeys.isEmpty())
    }
}
