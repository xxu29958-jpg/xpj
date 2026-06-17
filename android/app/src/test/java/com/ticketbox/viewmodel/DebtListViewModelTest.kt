package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
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
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DebtListViewModelTest {

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
    fun initLoadsDebtsAndReflectsRole() = runTest(dispatcher) {
        val repo = FakeDebtActions(canModify = false, listResult = Result.success(listOf(sampleDebt())))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertEquals(1, viewModel.state.value.debts.size)
        assertEquals(false, viewModel.state.value.canModify)
        assertEquals(false, viewModel.state.value.isLoading)
    }

    @Test
    fun refreshFailureSetsError() = runTest(dispatcher) {
        val repo = FakeDebtActions(listResult = Result.failure(RuntimeException("offline")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.debts.isEmpty())
        assertTrue(viewModel.state.value.error != null)
    }

    @Test
    fun submitDraftCreatesThenResetsFlashesAndRefetches() = runTest(dispatcher) {
        val repo = FakeDebtActions(createResult = Result.success(sampleDebt("created")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()
        val listCallsAfterInit = repo.listCalls

        viewModel.updateDraftDirection(DebtDirections.OWED_TO_ME)
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("123.45")
        viewModel.submitDraft()
        advanceUntilIdle()

        val draft = repo.createDrafts.single()
        assertEquals(DebtDirections.OWED_TO_ME, draft.direction)
        assertEquals("小王", draft.counterpartyLabel)
        assertEquals(12_345L, draft.principalAmountCents)
        // Success → draft reset, flash shown, list re-fetched.
        assertEquals("", viewModel.state.value.addDraft.counterpartyLabel)
        assertTrue(viewModel.state.value.flashMessage != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
        assertTrue(repo.listCalls > listCallsAfterInit)
    }

    @Test
    fun submitDraftWithBlankCounterpartyShowsValidationWithoutCreate() = runTest(dispatcher) {
        val repo = FakeDebtActions()
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.addDraft.validationError != null)
        assertTrue(repo.createDrafts.isEmpty())
    }

    @Test
    fun submitDraftWithNonPositiveAmountShowsValidationWithoutCreate() = runTest(dispatcher) {
        val repo = FakeDebtActions()
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        // Valid counterparty but a non-positive amount → the amount arm of the submit guard.
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("0")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.addDraft.validationError != null)
        assertTrue(repo.createDrafts.isEmpty())
    }

    @Test
    fun submitDraftFailureKeepsFormWithError() = runTest(dispatcher) {
        val repo = FakeDebtActions(createResult = Result.failure(RuntimeException("boom")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.addDraft.validationError != null)
        // The form retains the user's input so they can retry, not wiped.
        assertEquals("小王", viewModel.state.value.addDraft.counterpartyLabel)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun resetDraftClearsInput() = runTest(dispatcher) {
        val repo = FakeDebtActions()
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.resetDraft()

        assertEquals("", viewModel.state.value.addDraft.counterpartyLabel)
        assertEquals("", viewModel.state.value.addDraft.amountYuanInput)
    }

    @Test
    fun dismissFlashClearsMessage() = runTest(dispatcher) {
        val repo = FakeDebtActions(createResult = Result.success(sampleDebt("created")))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertTrue(viewModel.state.value.flashMessage != null)

        viewModel.dismissFlash()

        assertNull(viewModel.state.value.flashMessage)
    }

    @Test
    fun reloadClearsPriorLedgerDebtsThenRefetches() = runTest(dispatcher) {
        val repo = FakeDebtActions(listResult = Result.success(listOf(sampleDebt("a"))))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()
        assertEquals("a", viewModel.state.value.debts.single().publicId)

        // Simulate a ledger switch: the cached VM must not show the old ledger's debts.
        repo.listResult = Result.success(listOf(sampleDebt("b")))
        viewModel.reload()
        assertTrue(viewModel.state.value.debts.isEmpty()) // synchronous clear before the refetch
        advanceUntilIdle()

        assertEquals("b", viewModel.state.value.debts.single().publicId)
    }

    @Test
    fun staleRefreshDoesNotRevertAfterCreate() = runTest(dispatcher) {
        // A slow earlier refresh must not blank out the list after the user just added a debt.
        val repo = FakeDebtActions(
            listResult = Result.success(emptyList()),
            createResult = Result.success(sampleDebt("new")),
        )
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle() // init refresh → debts = []

        // A slow refresh stalls inside listDebts() (it captured the pre-create empty list)...
        val gate = CompletableDeferred<Unit>()
        repo.listGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then the user creates a debt; submitDraft's success refresh delivers the new list.
        repo.listGate = null
        repo.listResult = Result.success(listOf(sampleDebt("new")))
        viewModel.updateDraftCounterparty("小王")
        viewModel.updateDraftAmount("100")
        viewModel.submitDraft()
        advanceUntilIdle()
        assertEquals("new", viewModel.state.value.debts.single().publicId)

        // Release the now-stale refresh; its empty snapshot must NOT revert the just-created list.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals("new", viewModel.state.value.debts.single().publicId)
    }

    @Test
    fun staleRefreshDoesNotClobberReloadedLedger() = runTest(dispatcher) {
        // Ledger switch: a slow prior refresh must not show the old ledger's debts under the new one.
        val repo = FakeDebtActions(listResult = Result.success(listOf(sampleDebt("ledgerA"))))
        val viewModel = DebtListViewModel(repo)
        advanceUntilIdle()

        // A slow refresh stalls (it captured ledger A's debts)...
        val gate = CompletableDeferred<Unit>()
        repo.listGate = gate
        viewModel.refresh()
        runCurrent()

        // ...then a ledger switch reloads with ledger B's debts.
        repo.listGate = null
        repo.listResult = Result.success(listOf(sampleDebt("ledgerB")))
        viewModel.reload()
        advanceUntilIdle()
        assertEquals("ledgerB", viewModel.state.value.debts.single().publicId)

        // Release the stale refresh; ledger A's debts must NOT leak back under ledger B.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals("ledgerB", viewModel.state.value.debts.single().publicId)
        assertEquals(false, viewModel.state.value.isLoading)
    }
}

private class FakeDebtActions(
    private val canModify: Boolean = true,
    var listResult: Result<List<Debt>> = Result.success(emptyList()),
    var createResult: Result<Debt> = Result.success(sampleDebt()),
) : DebtActions {
    val createDrafts = mutableListOf<DebtDraft>()
    var listCalls = 0

    /** When set, listDebts() stalls until completed — used to interleave a slow load. */
    var listGate: CompletableDeferred<Unit>? = null

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun listDebts(): Result<List<Debt>> {
        listCalls++
        // Capture the result at entry so a stalled load returns the snapshot it started with, even
        // if a newer load swaps listResult in the meantime.
        val captured = listResult
        listGate?.await()
        return captured
    }

    override suspend fun getDebt(publicId: String): Result<Debt> = Result.success(sampleDebt(publicId))

    override suspend fun createDebt(draft: DebtDraft): Result<Debt> {
        createDrafts += draft
        return createResult
    }

    override suspend fun recordRepayment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
    ): Result<Debt> = Result.success(sampleDebt(publicId))

    override suspend fun recordAdjustment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
        reason: String,
    ): Result<Debt> = Result.success(sampleDebt(publicId))

    override suspend fun voidDebt(
        publicId: String,
        expectedRowVersion: Long,
        reason: String,
    ): Result<Debt> = Result.success(sampleDebt(publicId))
}

private fun sampleDebt(publicId: String = "debt-1"): Debt = Debt(
    publicId = publicId,
    ledgerId = "owner",
    direction = DebtDirections.I_OWE,
    counterpartyType = DebtCounterpartyTypes.EXTERNAL,
    counterpartyAccountId = null,
    counterpartyLabel = "房东",
    principalAmountCents = 50_000,
    remainingAmountCents = 50_000,
    paidAmountCents = 0,
    status = DebtLinkStatuses.OPEN,
    sourceType = DebtSourceTypes.MANUAL,
    sourceId = null,
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-15T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = 1,
)
