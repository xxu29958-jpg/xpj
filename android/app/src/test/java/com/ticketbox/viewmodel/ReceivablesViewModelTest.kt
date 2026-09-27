package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.ReceivablesActions
import com.ticketbox.data.repository.DebtReadResourceDenial
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtCounterpartyTypes
import com.ticketbox.domain.model.DebtDirections
import com.ticketbox.domain.model.DebtLinkStatuses
import com.ticketbox.domain.model.DebtSourceTypes
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.cancel
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
import kotlin.test.assertNull
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class ReceivablesViewModelTest {

    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test fun resourceRefusalDuringColdOrRefreshReadContinuesOtherPersonalReceivablesAndRejectsLateRows() = runTest(dispatcher) {
        for (cold in listOf(true, false)) {
            val other = sampleReceivable("kept").copy(homeCurrencyCode = "JPY", originalCurrencyCode = "JPY")
            val actions = FakeReceivablesActions(Result.success(listOf(other.copy(publicId = "gone"), other)))
            val gate = CompletableDeferred<Unit>()
            if (cold) actions.gate = gate
            val vm = ReceivablesViewModel(actions, FakeDebtWriteActions())
            advanceUntilIdle()
            if (!cold) {
                actions.gate = gate
                vm.refresh()
                runCurrent()
            }
            assertTrue(vm.state.value.isLoading)
            val current = other.copy(rowVersion = 9, remainingAmountCents = 7_000)
            actions.result = Result.success(listOf(current))
            actions.gate = null
            try {
                actions.resourceDenials.emit(DebtReadResourceDenial(adjustmentBinding(), "gone",
                    RepositoryException("记录不存在", httpStatusCode = 404, errorCode = "debt_not_found"), 1))
                advanceUntilIdle()
                assertEquals(listOf(current), vm.state.value.receivables)
                assertEquals(false, vm.state.value.isLoading)
                assertNull(vm.state.value.error)
            } finally { gate.complete(Unit) }
            advanceUntilIdle()
            assertEquals(listOf(current), vm.state.value.receivables, "The late personal list cannot revive the refused resource or its old balance")
            assertEquals("JPY", vm.state.value.receivables.single().homeCurrencyCode)
            assertEquals(false, vm.state.value.receivables.single().viewerIsDebtor)
            assertNull(vm.state.value.receivables.single().ledgerId)
            vm.viewModelScope.cancel()
        }
    }

    @Test
    fun initLoadsAndSortsActiveFirst() = runTest(dispatcher) {
        // The server returns status.asc (cleared before open); the VM must re-sort active-first.
        val repo = FakeReceivablesActions(
            result = Result.success(
                listOf(
                    sampleReceivable("cleared", DebtLinkStatuses.CLEARED),
                    sampleReceivable("open", DebtLinkStatuses.OPEN),
                ),
            ),
        )
        val viewModel = ReceivablesViewModel(repo, writes = FakeDebtWriteActions())
        advanceUntilIdle()

        assertEquals(listOf("open", "cleared"), viewModel.state.value.receivables.map { it.publicId })
        assertEquals(false, viewModel.state.value.isLoading)
        assertNull(viewModel.state.value.error)
    }

    @Test
    fun refreshFailureSetsErrorAndClearsLoading() = runTest(dispatcher) {
        val repo = FakeReceivablesActions(result = Result.failure(RuntimeException("offline")))
        val viewModel = ReceivablesViewModel(repo, writes = FakeDebtWriteActions())
        advanceUntilIdle()

        assertTrue(viewModel.state.value.receivables.isEmpty())
        assertTrue(viewModel.state.value.error != null)
        assertEquals(false, viewModel.state.value.isLoading)
    }

    @Test
    fun staleRefreshDoesNotClobberNewerData() = runTest(dispatcher) {
        // A slow earlier refresh must not overwrite a newer one (loadGeneration guard).
        val repo = FakeReceivablesActions(result = Result.success(listOf(sampleReceivable("first"))))
        val viewModel = ReceivablesViewModel(repo, writes = FakeDebtWriteActions())
        advanceUntilIdle()

        // A slow refresh stalls inside listReceivables (it captured the "first" snapshot)...
        val gate = CompletableDeferred<Unit>()
        repo.gate = gate
        viewModel.refresh()
        runCurrent()

        // ...then a newer refresh delivers fresh data and completes.
        repo.gate = null
        repo.result = Result.success(listOf(sampleReceivable("second")))
        viewModel.refresh()
        advanceUntilIdle()
        assertEquals("second", viewModel.state.value.receivables.single().publicId)

        // Release the now-stale refresh; its snapshot must NOT revert the newer data.
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals("second", viewModel.state.value.receivables.single().publicId)
        assertEquals(false, viewModel.state.value.isLoading)
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @Test
    fun terminalRefreshFailureCannotBeClearedByAnEarlierReceivablesRead() = runTest(dispatcher) {
        for (terminal in listOf(PendingMutationStatus.Done, PendingMutationStatus.Abandoned)) {
            val original = sampleReceivable("debt-1").copy(rowVersion = 7, ledgerId = "owner")
            val repo = FakeReceivablesActions(Result.success(listOf(original)))
            val writes = FakeDebtWriteActions()
            val vm = ReceivablesViewModel(repo, writes)
            try {
                advanceUntilIdle()
                val oldRead = CompletableDeferred<Unit>()
                repo.gate = oldRead
                vm.refresh()
                runCurrent()
                repo.gate = null
                repo.result = Result.failure(IllegalStateException("terminal refresh failed"))
                writes.rows.value = listOf(pendingAdjustment(status = terminal))
                advanceUntilIdle()
                assertNotNull(vm.state.value.error)
                oldRead.complete(Unit)
                advanceUntilIdle()
                assertNotNull(vm.state.value.error)
                assertEquals(listOf(original), vm.state.value.receivables)
                val current = original.copy(rowVersion = if (terminal == PendingMutationStatus.Done) 8L else 7L)
                repo.result = Result.success(listOf(current))
                vm.refresh()
                advanceUntilIdle()
                assertNull(vm.state.value.error)
                assertEquals(listOf(current), vm.state.value.receivables)
            } finally {
                vm.viewModelScope.coroutineContext.job.cancelAndJoin()
            }
        }
    }

    @Test
    fun sortReceivablesActiveFirstPutsOpenBeforeResolved() {
        val cleared = sampleReceivable("c", DebtLinkStatuses.CLEARED)
        val open = sampleReceivable("o", DebtLinkStatuses.OPEN)
        val voided = sampleReceivable("v", DebtLinkStatuses.VOIDED)

        // Open first; cleared/voided recede to the bottom. Removing the sort would leave the
        // server's status.asc order (cleared, open, voided) and fail this pin.
        val sorted = sortReceivablesActiveFirst(listOf(cleared, open, voided))

        assertEquals(listOf("o", "c", "v"), sorted.map { it.publicId })
    }

    @Test
    fun sortReceivablesActiveFirstIsStableWithinStatus() {
        // Two open receivables keep their incoming (server created) order within the same rank.
        val first = sampleReceivable("first", DebtLinkStatuses.OPEN)
        val second = sampleReceivable("second", DebtLinkStatuses.OPEN)

        val sorted = sortReceivablesActiveFirst(listOf(first, second))

        assertEquals(listOf("first", "second"), sorted.map { it.publicId })
    }
    @Test fun refusalRejectsLateReceivablesButResourceDenialKeepsOtherRows() = runTest(dispatcher) {
        val actions = FakeReceivablesActions(Result.success(listOf(sampleReceivable("gone"), sampleReceivable("kept"))))
        val writes = FakeDebtWriteActions()
        val model = ReceivablesViewModel(actions, writes)
        advanceUntilIdle()
        actions.resourceDenials.emit(com.ticketbox.data.repository.DebtReadResourceDenial(requireNotNull(writes.currentAccess()).binding,
            "gone", com.ticketbox.data.repository.RepositoryException("不存在", httpStatusCode = 404), 1))
        advanceUntilIdle()
        assertEquals(listOf("kept"), model.state.value.receivables.map { it.publicId })
        val gate = CompletableDeferred<Unit>()
        actions.gate = gate
        model.refresh()
        runCurrent()
        actions.readDenials.emit(com.ticketbox.data.repository.SnapshotAccessDenial(requireNotNull(writes.currentAccess()).binding,
            com.ticketbox.data.repository.RepositoryException("无权查看", httpStatusCode = 403), 1))
        gate.complete(Unit)
        advanceUntilIdle()
        assertTrue(model.state.value.receivables.isEmpty())
        assertEquals(null, model.state.value.fetchedAt)
    }

}

private class FakeReceivablesActions(
    var result: Result<List<Debt>> = Result.success(emptyList()),
) : ReceivablesActions {
    val readDenials = kotlinx.coroutines.flow.MutableSharedFlow<com.ticketbox.data.repository.SnapshotAccessDenial>()
    val resourceDenials = kotlinx.coroutines.flow.MutableSharedFlow<com.ticketbox.data.repository.DebtReadResourceDenial>()
    override fun observeReadAccessDenials() = readDenials
    override fun observeResourceDenials() = resourceDenials
    /** When set, listReceivables() stalls until completed — used to interleave a slow load. */
    var gate: CompletableDeferred<Unit>? = null
    var listCalls = 0

    override suspend fun listReceivables(): Result<com.ticketbox.data.repository.ReadSnapshot<List<Debt>>> {
        listCalls++
        // Capture at entry so a stalled load returns the snapshot it started with, even if a newer
        // load swaps `result` in the meantime.
        val captured = result
        gate?.await()
        return captured.map { debtReadSnapshot(it) }
    }
}

/** A cross-ledger member receivable (creditor side): ledger redacted (§5.2), viewer is the creditor. */
private fun sampleReceivable(publicId: String, status: String = DebtLinkStatuses.OPEN): Debt = Debt(
    publicId = publicId,
    ledgerId = null,
    direction = DebtDirections.I_OWE, // owner-relative; the owner is the debtor
    counterpartyType = DebtCounterpartyTypes.MEMBER,
    counterpartyAccountId = 7L,
    counterpartyLabel = "小王",
    principalAmountCents = 12_000,
    remainingAmountCents = if (status == DebtLinkStatuses.OPEN) 12_000 else 0,
    paidAmountCents = if (status == DebtLinkStatuses.OPEN) 0 else 12_000,
    status = status,
    sourceType = DebtSourceTypes.BILL_SPLIT,
    sourceId = "inv-1",
    homeCurrencyCode = "CNY",
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-18T00:00:00Z",
    updatedAt = "2026-06-18T00:00:00Z",
    rowVersion = 1,
    viewerIsDebtor = false,
)
