package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.DebtCreationQueueSnapshot
import com.ticketbox.domain.model.UiText
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
        val viewModel = DebtListViewModel(repository, repository)
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
        val viewModel = DebtListViewModel(repository, repository)
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

    @Test
    fun oldBindingAcceptanceCannotClearTheNewLedgerFormOrAnnounceItsSuccess() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val repository = readyRepository(gate)
        val viewModel = DebtListViewModel(repository, repository)
        advanceUntilIdle()
        fillDraft(viewModel)
        viewModel.submitDraft()
        runCurrent()

        val oldAccess = requireNotNull(repository.access.value)
        repository.access.value = oldAccess.copy(binding = oldAccess.binding.copy(ledgerId = "next", bindingRevision = "binding-2"))
        runCurrent()
        viewModel.updateDraftCounterparty("新账本的记录")
        viewModel.updateDraftAmount("55.00")
        gate.complete(Unit)
        advanceUntilIdle()

        assertEquals("新账本的记录", viewModel.state.value.addDraft.counterpartyLabel)
        assertEquals("55.00", viewModel.state.value.addDraft.amountYuanInput)
        assertEquals(false, viewModel.state.value.addAccepted)
        assertEquals(null, viewModel.state.value.flashMessage)
    }

    @Test
    fun completedIntentRefreshesCanonicalListEvenWhenPendingEmissionWasTooFastToObserve() = runTest(dispatcher) {
        val repository = FakeDebtActions().apply { listCapability = "CNY" }
        val viewModel = DebtListViewModel(repository, repository)
        advanceUntilIdle()
        val readsBefore = repository.listCalls
        repository.listResult = Result.success(listOf(sampleDebt("server-debt")))

        repository.pendingCreations.value = DebtCreationQueueSnapshot(
            binding = repository.access.value?.binding,
            completedIntentIds = setOf(7L),
        )
        advanceUntilIdle()

        assertTrue(repository.listCalls > readsBefore)
        assertEquals("server-debt", viewModel.state.value.debts.single().publicId)
        assertEquals(1, viewModel.state.value.creationSettlementRevision)
        assertEquals(false, viewModel.state.value.addAccepted)
    }

    @Test
    fun localAcceptanceNeverInventsACanonicalDebt() = runTest(dispatcher) {
        val repository = FakeDebtActions().apply { listCapability = "CNY" }
        val viewModel = DebtListViewModel(repository, repository)
        advanceUntilIdle()
        fillDraft(viewModel)
        viewModel.submitDraft()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.addAccepted)
        assertTrue(viewModel.state.value.debts.isEmpty())
        assertEquals(UiText.res(R.string.debt_create_local_saved), viewModel.state.value.flashMessage)
        assertEquals(0, viewModel.state.value.creationSettlementRevision)
    }

    private fun fillDraft(viewModel: DebtListViewModel) {
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("123.45")
        viewModel.updateDraftNote("出差垫付车费")
    }
}
