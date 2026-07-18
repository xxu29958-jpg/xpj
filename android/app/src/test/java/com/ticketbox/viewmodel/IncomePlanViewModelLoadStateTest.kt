package com.ticketbox.viewmodel

import com.ticketbox.data.repository.IncomePlanActions
import com.ticketbox.data.repository.IncomePlanDraft
import com.ticketbox.data.repository.IncomePlanListing
import com.ticketbox.data.repository.IncomePlanPatch
import com.ticketbox.domain.model.IncomeFrequency
import com.ticketbox.domain.model.IncomePlan
import com.ticketbox.domain.model.IncomePlanStatus
import com.ticketbox.domain.model.IncomeSourceType
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
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
class IncomePlanViewModelLoadStateTest {

    private val dispatcher = StandardTestDispatcher()

    @BeforeTest
    fun setup() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        Dispatchers.resetMain()
    }

    @Test
    fun activeFailureMarksFailedWithoutConfirmingEmpty() = runTest(dispatcher) {
        val viewModel = IncomePlanViewModel(
            LoadStateIncomePlanRepository(
                activeResult = Result.failure(RuntimeException("offline")),
            ),
        )
        advanceUntilIdle()

        val state = viewModel.state.value
        assertEquals(IncomePlanLoadState.Failed, state.loadState)
        assertTrue(state.activePlans.isEmpty())
        assertTrue(state.archivedPlans.isEmpty())
        assertNotNull(state.error)
    }

    @Test
    fun loadedEmptyAndArchivedFailureStayExplicit() = runTest(dispatcher) {
        val loadedEmpty = IncomePlanViewModel(LoadStateIncomePlanRepository())
        advanceUntilIdle()
        assertEquals(IncomePlanLoadState.Loaded, loadedEmpty.state.value.loadState)
        assertNull(loadedEmpty.state.value.error)

        val archivedFailure = IncomePlanViewModel(
            LoadStateIncomePlanRepository(
                archivedResult = Result.failure(RuntimeException("archived offline")),
            ),
        )
        advanceUntilIdle()

        assertEquals(IncomePlanLoadState.Loaded, archivedFailure.state.value.loadState)
        assertNotNull(archivedFailure.state.value.error)
    }

    @Test
    fun ledgerSwitchClearsOldFactsRechecksPermissionAndRejectsLateOldResponse() = runTest(dispatcher) {
        val repository = SwitchingIncomePlanRepository()
        val viewModel = IncomePlanViewModel(repository)
        advanceUntilIdle()
        assertEquals(listOf("ledger-a"), viewModel.state.value.activePlans.map(IncomePlan::publicId))
        assertTrue(viewModel.state.value.canModify)

        // Start a refresh owned by ledger A and hold it in flight.
        viewModel.refresh()
        runCurrent()
        assertEquals(2, repository.activeCalls)

        // Switching to ledger B must clear A synchronously before B returns and must
        // derive permission from the new binding rather than the prior successful load.
        repository.canModify = false
        repository.activeLedgerId.value = "ledger-b"
        runCurrent()

        val switching = viewModel.state.value
        assertTrue(switching.isLoading)
        assertEquals(IncomePlanLoadState.Loading, switching.loadState)
        assertFalse(switching.canModify)
        assertTrue(switching.activePlans.isEmpty())
        assertTrue(switching.archivedPlans.isEmpty())
        assertEquals(IncomePlanMonthSummary(), switching.currentMonthSummary)
        assertEquals(3, repository.activeCalls)

        repository.newLedgerGate.complete(
            Result.success(IncomePlanListing(listOf(plan("ledger-b")), 100L)),
        )
        runCurrent()
        assertEquals(listOf("ledger-b"), viewModel.state.value.activePlans.map(IncomePlan::publicId))

        // The earlier ledger-A response completes last. Generation ownership must
        // discard it instead of putting A back onto the B screen.
        repository.staleLedgerGate.complete(
            Result.success(IncomePlanListing(listOf(plan("late-ledger-a")), 100L)),
        )
        advanceUntilIdle()
        assertEquals(listOf("ledger-b"), viewModel.state.value.activePlans.map(IncomePlan::publicId))
        assertFalse(viewModel.state.value.canModify)
    }
}

private class LoadStateIncomePlanRepository(
    private val activeResult: Result<IncomePlanListing> = Result.success(IncomePlanListing(emptyList(), 0L)),
    private val archivedResult: Result<List<IncomePlan>> = Result.success(emptyList()),
) : IncomePlanActions {
    override fun canModifyLedger(): Boolean = true

    override suspend fun listActive(): Result<IncomePlanListing> = activeResult

    override suspend fun listIncluding(status: IncomePlanStatus): Result<List<IncomePlan>> = archivedResult

    override suspend fun create(draft: IncomePlanDraft): Result<IncomePlan> = Result.success(plan("created"))

    override suspend fun update(publicId: String, patch: IncomePlanPatch): Result<IncomePlan> =
        Result.success(plan(publicId))

    override suspend fun archive(publicId: String, expectedRowVersion: Long): Result<IncomePlan> =
        Result.success(plan(publicId, status = IncomePlanStatus.ARCHIVED))

    override suspend fun restore(publicId: String, expectedRowVersion: Long): Result<IncomePlan> =
        Result.success(plan(publicId))
}

private class SwitchingIncomePlanRepository : IncomePlanActions {
    val activeLedgerId = MutableStateFlow<String?>("ledger-a")
    val staleLedgerGate = CompletableDeferred<Result<IncomePlanListing>>()
    val newLedgerGate = CompletableDeferred<Result<IncomePlanListing>>()
    var canModify = true
    var activeCalls = 0
        private set

    override fun canModifyLedger(): Boolean = canModify

    override fun observeActiveLedgerId(): Flow<String?> = activeLedgerId

    override suspend fun listActive(): Result<IncomePlanListing> {
        activeCalls += 1
        return when (activeCalls) {
            1 -> Result.success(IncomePlanListing(listOf(plan("ledger-a")), 100L))
            2 -> staleLedgerGate.await()
            else -> newLedgerGate.await()
        }
    }

    override suspend fun listIncluding(status: IncomePlanStatus): Result<List<IncomePlan>> =
        Result.success(emptyList())

    override suspend fun create(draft: IncomePlanDraft): Result<IncomePlan> =
        Result.success(plan("created"))

    override suspend fun update(publicId: String, patch: IncomePlanPatch): Result<IncomePlan> =
        Result.success(plan(publicId))

    override suspend fun archive(publicId: String, expectedRowVersion: Long): Result<IncomePlan> =
        Result.success(plan(publicId, status = IncomePlanStatus.ARCHIVED))

    override suspend fun restore(publicId: String, expectedRowVersion: Long): Result<IncomePlan> =
        Result.success(plan(publicId))
}

private fun plan(
    publicId: String,
    status: IncomePlanStatus = IncomePlanStatus.ACTIVE,
): IncomePlan = IncomePlan(
    publicId = publicId,
    label = publicId,
    sourceType = IncomeSourceType.SALARY,
    frequency = IncomeFrequency.MONTHLY,
    incomeMonth = null,
    amountCents = 100L,
    payDay = 1,
    status = status,
    createdAt = "2026-05-01T00:00:00Z",
    updatedAt = "2026-05-01T00:00:00Z",
    rowVersion = 1L,
    archivedAt = if (status == IncomePlanStatus.ARCHIVED) "2026-05-02T00:00:00Z" else null,
)
