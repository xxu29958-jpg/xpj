package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.repository.LedgerAccessContext
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
import kotlin.test.assertTrue
import kotlin.test.assertNotEquals

class MemberRepaymentProposalCommandContinuityTest {
    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setUp() { Dispatchers.setMain(dispatcher) }

    @AfterTest
    fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun returningToAnUnsubmittedMemberRepaymentKeepsItsRawInput() = runTest(dispatcher) {
        val repository = ProposalTestActions()
        val viewModel = MemberRepaymentProposalViewModel(repository)
        val task = memberDebtTask("d1")
        viewModel.load(task)
        advanceUntilIdle()
        viewModel.openForm(task, ProposalForm.Propose, debt = sampleMemberDebt().copy(publicId = task.debtPublicId))
        viewModel.updateAmount(task, "0200.")
        viewModel.updateNote(task, "  本期先还一部分  ")
        viewModel.dismissForm(task)
        viewModel.load(memberDebtTask("d2"))
        advanceUntilIdle()
        viewModel.load(task)
        advanceUntilIdle()
        viewModel.openForm(task, ProposalForm.Propose, debt = sampleMemberDebt().copy(publicId = task.debtPublicId))

        assertEquals("0200.", viewModel.state.value.amountInput)
        assertEquals("  本期先还一部分  ", viewModel.state.value.noteInput)
        assertEquals(emptyList(), repository.commandKeys)
    }

    @Test
    fun lostConfirmationReplyCannotBecomeANewRequestAfterTheDebtRefreshes() = runTest(dispatcher) {
        val repository = ProposalTestActions(
            listResult = Result.success(listOf(sampleMemberProposal())),
            confirmResult = Result.failure(RepositoryException("reply lost")),
        )
        val viewModel = MemberRepaymentProposalViewModel(repository)
        val task = memberDebtTask("d1")
        viewModel.load(task)
        advanceUntilIdle()
        viewModel.openForm(task, ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.updateAmount(task, "150.00")
        viewModel.submit(task, expectedRowVersion = 7, currency = CurrencyCode.CNY)
        advanceUntilIdle()
        val original = repository.confirmCalls.single()
        viewModel.dismissForm(task)
        viewModel.openForm(task, ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.updateAmount(task, "180.00")
        viewModel.submit(task, expectedRowVersion = 8, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        assertEquals(listOf(original, original), repository.confirmCalls)
        assertEquals(1, repository.commandKeys.distinct().size)
        assertNull(viewModel.state.value.committedDebt)
    }

    @Test
    fun originalPaymentDateAndCalendarSurviveRecreationAndAnUnknownResult() = runTest(dispatcher) {
        val repository = ProposalTestActions(proposalResult = Result.failure(RepositoryException("reply lost")))
        val saved = SavedStateHandle()
        val task = memberDebtTask("d1")
        val first = MemberRepaymentProposalViewModel(repository, saved)
        val originalDebt = sampleMemberDebt().copy(ledgerId = null)
        first.load(task)
        advanceUntilIdle()
        first.openForm(task, ProposalForm.Propose, debt = originalDebt)
        first.updateAmount(task, "200.00")
        first.updatePaymentDate(task, "2026-03-")
        first.dismissForm(task)
        val restoredSaved = SavedStateHandle(saved.keys().associateWith { saved.get<Any?>(it) })
        val restored = MemberRepaymentProposalViewModel(repository, restoredSaved)
        restored.load(task)
        advanceUntilIdle()
        val changedCalendar = originalDebt.copy(repaymentCalendar = com.ticketbox.domain.model.DebtRepaymentCalendar(4, "Pacific/Honolulu"))
        restored.openForm(task, ProposalForm.Propose, debt = changedCalendar)
        assertEquals("2026-03-", restored.state.value.paymentTime?.date)
        restored.submit(task, 7, CurrencyCode.CNY)
        assertTrue(repository.proposeCalls.isEmpty())
        restored.updatePaymentDate(task, "2026-03-08")
        restored.submit(task, 7, CurrencyCode.CNY)
        advanceUntilIdle()
        val firstCall = repository.proposeCalls.single()
        val originalTime = assertNotNull(firstCall.timeInput)
        assertEquals("date_only", originalTime.precision)
        assertEquals("2026-03-08", originalTime.userLocalDate)
        assertEquals("2026-03-08", originalTime.accountingDate)
        assertEquals(3L, originalTime.calendarRevision)
        assertEquals("Asia/Shanghai", originalTime.sourceTimezone)
        assertNull(originalTime.instantUtc)
        val retry = MemberRepaymentProposalViewModel(repository,
            SavedStateHandle(restoredSaved.keys().associateWith { restoredSaved.get<Any?>(it) }))
        retry.load(task)
        advanceUntilIdle()
        retry.openForm(task, ProposalForm.Propose, debt = changedCalendar)
        retry.updatePaymentDate(task, "2026-10-12")
        retry.retryOriginal(task)
        advanceUntilIdle()
        assertEquals(listOf(firstCall, firstCall), repository.proposeCalls)
        assertEquals(1, repository.commandKeys.distinct().size)
        assertEquals("2026-03-08", retry.state.value.paymentTime?.date)
    }

    @Test
    fun restoredOriginalConfirmationKeepsItsOwnerCurrencyVersionAndKeyUntilAcknowledged() = runTest(dispatcher) {
        val repository = ProposalTestActions(
            listResult = Result.success(listOf(sampleMemberProposal(proposedAmountCents = 500).copy(homeCurrencyCode = "JPY"))),
            confirmResult = Result.failure(RepositoryException("reply lost")),
        )
        val saved = SavedStateHandle()
        val original = MemberRepaymentProposalViewModel(repository, saved)
        val task = memberDebtTask("d1")
        original.load(task)
        advanceUntilIdle()
        original.openForm(task, ProposalForm.Confirm, original.state.value.pendingProposal)
        original.updateAmount(task, "450")
        original.submit(task, 7, CurrencyCode.JPY)
        advanceUntilIdle()
        val firstCall = repository.confirmCalls.single()
        val firstKey = repository.commandKeys.single()
        val restored = MemberRepaymentProposalViewModel(repository, SavedStateHandle(saved.keys().associateWith { saved.get<Any?>(it) }))
        val other = task.copy(binding = task.binding.copy(sessionGeneration = "new-session"))
        repository.access.value = LedgerAccessContext(other.binding, true)
        advanceUntilIdle()
        restored.load(other)
        advanceUntilIdle()
        assertEquals("", restored.state.value.amountInput)
        assertNull(restored.state.value.originalAttempt)
        repository.access.value = LedgerAccessContext(task.binding, true)
        repository.listResult = Result.success(emptyList())
        restored.load(task)
        advanceUntilIdle()
        assertEquals("JPY", restored.state.value.formCurrencyCode)
        assertEquals("450", restored.state.value.amountInput)
        restored.forgive(task, 9)
        assertTrue(repository.forgiveCalls.isEmpty())
        repository.confirmResult = Result.success(sampleMemberDebt())
        restored.retryOriginal(task)
        advanceUntilIdle()
        assertEquals(listOf(firstCall, firstCall), repository.confirmCalls)
        assertEquals(listOf(firstKey, firstKey), repository.commandKeys)
        assertNotNull(restored.state.value.committedDebt)
        assertNull(restored.state.value.originalAttempt)
    }

    @Test
    fun rejectedConfirmationRequiresExplicitReviewBeforeUsingTheNewVersion() = runTest(dispatcher) {
        val repository = ProposalTestActions(
            listResult = Result.success(listOf(sampleMemberProposal())),
            confirmResult = Result.failure(RepositoryException("changed", errorCode = "state_conflict", httpStatusCode = 409)),
        )
        val viewModel = MemberRepaymentProposalViewModel(repository)
        val task = memberDebtTask("d1")
        viewModel.load(task)
        advanceUntilIdle()
        viewModel.openForm(task, ProposalForm.Confirm, viewModel.state.value.pendingProposal)
        viewModel.updateAmount(task, "150.00")
        viewModel.submit(task, 7, CurrencyCode.CNY)
        advanceUntilIdle()
        viewModel.updateAmount(task, "180.00")
        viewModel.retryOriginal(task)
        advanceUntilIdle()
        assertEquals("150.00", viewModel.state.value.amountInput)
        assertEquals(1, repository.confirmCalls.size)
        viewModel.reviewRejected(task, sampleMemberDebt().copy(rowVersion = 8))
        viewModel.updateAmount(task, "180.00")
        repository.confirmResult = Result.success(sampleMemberDebt())
        viewModel.submit(task, 8, CurrencyCode.CNY)
        advanceUntilIdle()
        assertEquals(listOf(7L, 8L), repository.confirmCalls.map { it.expectedRowVersion })
        assertEquals(listOf(15_000L, 18_000L), repository.confirmCalls.map { it.confirmedAmountCents })
        assertNotEquals(repository.commandKeys.first(), repository.commandKeys.last())
    }

    @Test
    fun repeatedSubmitKeepsOneActiveProposalCommand() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val repository = ProposalTestActions().apply { proposeGate = gate }
        val viewModel = MemberRepaymentProposalViewModel(repository)
        viewModel.load(memberDebtTask("d1"))
        advanceUntilIdle()
        viewModel.openForm(requireNotNull(viewModel.state.value.task), ProposalForm.Propose, debt = sampleMemberDebt().copy(publicId = requireNotNull(viewModel.state.value.task).debtPublicId))
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
        viewModel.openForm(requireNotNull(viewModel.state.value.task), ProposalForm.Propose, debt = sampleMemberDebt().copy(publicId = requireNotNull(viewModel.state.value.task).debtPublicId))
        viewModel.updateAmount(requireNotNull(viewModel.state.value.task), "200.00")
        viewModel.submit(requireNotNull(viewModel.state.value.task), expectedRowVersion = 1, currency = CurrencyCode.CNY)
        runCurrent()

        viewModel.load(memberDebtTask("d2"))
        advanceUntilIdle()
        viewModel.openForm(requireNotNull(viewModel.state.value.task), ProposalForm.Propose, debt = sampleMemberDebt().copy(publicId = requireNotNull(viewModel.state.value.task).debtPublicId))
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
        viewModel.openForm(requireNotNull(viewModel.state.value.task), ProposalForm.Propose, debt = sampleMemberDebt().copy(publicId = requireNotNull(viewModel.state.value.task).debtPublicId))
        viewModel.updateAmount(requireNotNull(viewModel.state.value.task), "200.00")
        viewModel.submit(requireNotNull(viewModel.state.value.task), expectedRowVersion = 1, currency = CurrencyCode.CNY)
        advanceUntilIdle()

        assertEquals(repository.proposalResult.getOrThrow(), viewModel.state.value.pendingProposal)
        assertNull(viewModel.state.value.activeForm)
        assertNotNull(viewModel.state.value.flashMessage)
        assertEquals(1L, viewModel.state.value.acknowledgedCommandRevision)
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals(1L, viewModel.state.value.acknowledgedCommandRevision)
    }
}
