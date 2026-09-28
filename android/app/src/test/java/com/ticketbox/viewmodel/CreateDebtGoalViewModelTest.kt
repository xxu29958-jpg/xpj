package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.data.repository.ReadSnapshot
import com.ticketbox.data.repository.SnapshotAccessDenial
import com.ticketbox.data.repository.DebtReadResourceDenial
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtBillSuggestion
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import androidx.lifecycle.viewModelScope
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableSharedFlow
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class CreateDebtGoalViewModelTest {

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
    fun returningToCreationRetainsRawNameAndSelectionForExplicitReview() = runTest(dispatcher) {
        val original = debt("original", "open")
        val other = debt("other", "open")
        val debts = FakeCreateDebtActions(listResult = Result.success(listOf(original, other)))
        val reports = FakeCreateGoalEdits()
        val vm = CreateDebtGoalViewModel(reports, debts, FakeDebtWriteActions())
        vm.reload()
        advanceUntilIdle()
        vm.updateName("  还清原来的欠款  ")
        vm.toggleDebt(original.publicId)
        assertTrue(vm.state.value.canSubmit)

        // The create screen calls reload again on reentry. A now-cleared debt
        // changes the readable candidates, not the user's unsubmitted selection.
        debts.listResult = Result.success(listOf(other))
        vm.reload()
        advanceUntilIdle()
        assertEquals("  还清原来的欠款  ", vm.state.value.name)
        assertEquals(setOf(original.publicId), vm.state.value.selectedDebtIds)
        assertEquals(listOf(other), vm.state.value.candidates)
        assertEquals(setOf(original.publicId), vm.state.value.unavailableSelectedDebtIds)
        assertFalse(vm.state.value.canSubmit)
        assertTrue(reports.createDebtGoalCalls.isEmpty())
        vm.removeUnavailableSelections()
        assertTrue(vm.state.value.selectedDebtIds.isEmpty())
        assertEquals("  还清原来的欠款  ", vm.state.value.name)
        vm.viewModelScope.cancel()
    }

    @Test fun resourceRefusalDuringColdOrRefreshReadRecoversOtherCandidatesWithoutReplacingTheForm() = runTest(dispatcher) {
        for (cold in listOf(true, false)) {
            val other = debt("kept", "open").copy(homeCurrencyCode = "JPY", originalCurrencyCode = "JPY")
            val actions = FakeCreateDebtActions(listResult = Result.success(listOf(other.copy(publicId = "gone"), other)))
            val reports = FakeCreateGoalEdits()
            val gate = CompletableDeferred<Unit>()
            if (cold) actions.listGate = gate
            val vm = CreateDebtGoalViewModel(reports, actions, FakeDebtWriteActions())
            vm.reload()
            advanceUntilIdle()
            vm.updateName("保留日元还债计划")
            if (!cold) {
                vm.toggleDebt("gone")
                actions.listGate = gate
                vm.refreshCandidates()
                runCurrent()
            }
            val selection = vm.state.value.selectedDebtIds
            assertTrue(vm.state.value.isLoadingDebts)
            val current = other.copy(rowVersion = 9, remainingAmountCents = 30_000)
            actions.listResult = Result.success(listOf(current))
            actions.listGate = null
            try {
                actions.resourceDenials.emit(DebtReadResourceDenial(adjustmentBinding(), "gone",
                    RepositoryException("记录不存在", httpStatusCode = 404, errorCode = "debt_not_found"), 1))
                advanceUntilIdle()
                assertEquals(listOf(current), vm.state.value.candidates)
                assertFalse(vm.state.value.isLoadingDebts)
                assertEquals(actions.fetchedAt, vm.state.value.fetchedAt)
                assertEquals("保留日元还债计划", vm.state.value.name)
                assertEquals(selection, vm.state.value.selectedDebtIds)
                assertEquals(selection, vm.state.value.unavailableSelectedDebtIds)
                assertFalse(vm.state.value.canSubmit)
            } finally { gate.complete(Unit) }
            advanceUntilIdle()
            assertEquals(listOf(current), vm.state.value.candidates, "The superseded list cannot revive the refused resource or old balances")
            assertEquals("JPY", vm.state.value.candidates.single().homeCurrencyCode)
            assertTrue(reports.createDebtGoalCalls.isEmpty())
            vm.viewModelScope.cancel()
        }
    }

    @Test
    fun cachedCandidatesAndDeniedRefreshPreserveTheNameAndExplicitSelection() = runTest(dispatcher) {
        val original = debt("original", "open")
        val other = debt("other", "open")
        val debts = FakeCreateDebtActions(listResult = Result.success(listOf(original, other)))
        debts.fromCache = true
        val reports = FakeCreateGoalEdits()
        val vm = CreateDebtGoalViewModel(reports, debts, FakeDebtWriteActions())
        vm.reload()
        advanceUntilIdle()
        vm.updateName("保留我的还债安排")
        vm.toggleDebt(original.publicId)
        assertTrue(vm.state.value.canSubmit, "A labeled cache does not remove an existing supported action")
        assertEquals(debts.fetchedAt, vm.state.value.fetchedAt)
        assertTrue(vm.state.value.fromCache)

        debts.resourceDenials.emit(DebtReadResourceDenial(adjustmentBinding(), original.publicId,
            RepositoryException("不可见", errorCode = "debt_not_found", httpStatusCode = 404), 1))
        advanceUntilIdle()
        assertEquals(listOf(other), vm.state.value.candidates)
        assertEquals(setOf(original.publicId), vm.state.value.unavailableSelectedDebtIds)
        assertEquals("保留我的还债安排", vm.state.value.name)
        assertFalse(vm.state.value.canSubmit)

        val oldRead = CompletableDeferred<Unit>()
        debts.listGate = oldRead
        vm.refreshCandidates()
        runCurrent()
        debts.denials.emit(SnapshotAccessDenial(adjustmentBinding(),
            RepositoryException("无权读取", httpStatusCode = 403), 2))
        advanceUntilIdle()
        oldRead.complete(Unit)
        advanceUntilIdle()
        assertTrue(vm.state.value.candidates.isEmpty(), "The late read cannot restore denied candidates")
        assertNull(vm.state.value.fetchedAt)
        assertEquals("保留我的还债安排", vm.state.value.name)
        assertEquals(setOf(original.publicId), vm.state.value.selectedDebtIds)
        vm.submit()
        advanceUntilIdle()
        assertTrue(reports.createDebtGoalCalls.isEmpty())

        debts.listGate = null
        debts.fromCache = false
        vm.refreshCandidates()
        advanceUntilIdle()
        assertTrue(vm.state.value.canSubmit)
        assertFalse(vm.state.value.fromCache)
    }

    @Test
    fun reloadLoadsOnlyOpenDebtsAndReflectsRole() = runTest(dispatcher) {
        val debts = FakeCreateDebtActions(
            canModify = false,
            listResult = Result.success(
                listOf(debt("open-1", "open"), debt("cleared-1", "cleared"), debt("voided-1", "voided")),
            ),
        )
        val viewModel = CreateDebtGoalViewModel(FakeCreateGoalEdits(canModify = false), debts, writes = FakeDebtWriteActions())
        viewModel.reload()
        advanceUntilIdle()

        // The picker tracks only OPEN debts (cleared → instant achieve, voided → review dead-end).
        assertEquals(listOf("open-1"), viewModel.state.value.candidates.map { it.publicId })
        assertFalse(viewModel.state.value.canModify)
        assertFalse(viewModel.state.value.isLoadingDebts)
    }

    @Test
    fun candidateRefreshRetainsDraftAfterFailureAndRecovery() = runTest(dispatcher) {
        val debts = FakeCreateDebtActions(listResult = Result.failure(RuntimeException("offline")))
        val reports = FakeCreateGoalEdits()
        val writes = FakeDebtWriteActions()
        val viewModel = CreateDebtGoalViewModel(reports, debts, writes)
        viewModel.reload()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.candidates.isEmpty())
        assertTrue(viewModel.state.value.loadError != null)
        val available = listOf(debt("open-1", "open"))
        debts.listResult = Result.success(available)
        viewModel.refreshCandidates()
        advanceUntilIdle()
        viewModel.updateName("保留原计划名称")
        viewModel.toggleDebt("open-1")

        debts.listResult = Result.failure(RuntimeException("offline after adjustment"))
        writes.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.Done))
        advanceUntilIdle()
        assertTrue(viewModel.state.value.loadError != null)
        assertFalse(viewModel.state.value.canSubmit)
        viewModel.submit()
        assertTrue(reports.createDebtGoalCalls.isEmpty())
        assertEquals("保留原计划名称", viewModel.state.value.name)
        assertEquals(setOf("open-1"), viewModel.state.value.selectedDebtIds)

        debts.listResult = Result.success(available)
        viewModel.refreshCandidates()
        advanceUntilIdle()

        assertNull(viewModel.state.value.loadError)
        assertEquals(available, viewModel.state.value.candidates)
        assertEquals("保留原计划名称", viewModel.state.value.name)
        assertEquals(setOf("open-1"), viewModel.state.value.selectedDebtIds)
        assertTrue(viewModel.state.value.canSubmit)
        assertTrue(reports.createDebtGoalCalls.isEmpty())
    }

    @Test
    fun toggleDebtAddsThenRemoves() = runTest(dispatcher) {
        val viewModel = createViewModel(listOf(debt("open-1", "open")))
        viewModel.reload()
        advanceUntilIdle()

        viewModel.toggleDebt("open-1")
        assertEquals(setOf("open-1"), viewModel.state.value.selectedDebtIds)
        viewModel.toggleDebt("open-1")
        assertTrue(viewModel.state.value.selectedDebtIds.isEmpty())
    }

    @Test
    fun submitWithBlankNameSetsValidationErrorWithoutApiCall() = runTest(dispatcher) {
        val reports = FakeCreateGoalEdits()
        val viewModel = CreateDebtGoalViewModel(reports, FakeCreateDebtActions(
            listResult = Result.success(listOf(debt("open-1", "open"))),
        ), writes = FakeDebtWriteActions())
        viewModel.reload()
        advanceUntilIdle()
        viewModel.toggleDebt("open-1") // selection present, but name is blank
        viewModel.updateName("   ")

        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.formError != null)
        assertTrue(reports.createDebtGoalCalls.isEmpty())
    }

    @Test
    fun submitWithNoSelectionSetsValidationErrorWithoutApiCall() = runTest(dispatcher) {
        val reports = FakeCreateGoalEdits()
        val viewModel = CreateDebtGoalViewModel(reports, FakeCreateDebtActions(
            listResult = Result.success(listOf(debt("open-1", "open"))),
        ), writes = FakeDebtWriteActions())
        viewModel.reload()
        advanceUntilIdle()
        viewModel.updateName("还清欠款") // name present, but nothing selected

        viewModel.submit()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.formError != null)
        assertTrue(reports.createDebtGoalCalls.isEmpty())
    }

    @Test
    fun submitSuccessSetsCreatedSignalAndPassesSelectedIdsInCandidateOrder() = runTest(dispatcher) {
        val reports = FakeCreateGoalEdits(createResult = Result.success(debtGoal("new-goal")))
        val debts = FakeCreateDebtActions(
            listResult = Result.success(
                listOf(debt("open-a", "open"), debt("open-b", "open"), debt("open-c", "open")),
            ),
        )
        val writes = FakeDebtWriteActions()
        val viewModel = CreateDebtGoalViewModel(reports, debts, writes)
        viewModel.reload()
        advanceUntilIdle()
        // Select out of candidate order; submit must still send candidate order.
        viewModel.toggleDebt("open-c")
        viewModel.toggleDebt("open-a")
        viewModel.updateName("  还清欠款  ")

        // A background correction clears a selected debt; never silently submit only the other id.
        debts.listResult = Result.success(listOf(debt("open-a", "open"), debt("open-c", "cleared")))
        writes.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.Done))
        advanceUntilIdle()
        assertEquals(setOf("open-a", "open-c"), viewModel.state.value.selectedDebtIds)
        assertEquals("  还清欠款  ", viewModel.state.value.name)
        assertFalse(viewModel.state.value.canSubmit)
        viewModel.submit()
        advanceUntilIdle()
        assertTrue(reports.createDebtGoalCalls.isEmpty())
        assertTrue(viewModel.state.value.formError != null)
        viewModel.removeUnavailableSelections()
        assertEquals(setOf("open-a"), viewModel.state.value.selectedDebtIds)
        assertEquals("  还清欠款  ", viewModel.state.value.name)

        debts.listResult = Result.success(listOf(debt("open-a", "open"), debt("open-c", "open")))
        writes.rows.value += pendingAdjustment(id = 2, status = PendingMutationStatus.Done)
        advanceUntilIdle()
        viewModel.toggleDebt("open-c")
        viewModel.submit()
        advanceUntilIdle()

        val call = reports.createDebtGoalCalls.single()
        assertEquals(adjustmentBinding(), reports.createDebtGoalBindings.single())
        assertEquals("还清欠款", call.name)
        assertEquals(listOf("open-a", "open-c"), call.debtPublicIds)
        assertEquals("new-goal", viewModel.state.value.createdPublicId)
        assertFalse(viewModel.state.value.isSubmitting)
    }

    @Test
    fun submitFailureSetsFormErrorAndClearsSubmitting() = runTest(dispatcher) {
        val reports = FakeCreateGoalEdits(createResult = Result.failure(RuntimeException("conflict")))
        val viewModel = CreateDebtGoalViewModel(reports, FakeCreateDebtActions(
            listResult = Result.success(listOf(debt("open-1", "open"))),
        ), writes = FakeDebtWriteActions())
        viewModel.reload()
        advanceUntilIdle()
        viewModel.toggleDebt("open-1")
        viewModel.updateName("还清欠款")

        viewModel.submit()
        advanceUntilIdle()

        assertTrue(reports.createDebtGoalCalls.size == 1)
        assertTrue(viewModel.state.value.formError != null)
        assertFalse(viewModel.state.value.isSubmitting)
        assertNull(viewModel.state.value.createdPublicId)
    }

    @Test
    fun consumeCreatedClearsTheOneShotSignal() = runTest(dispatcher) {
        val reports = FakeCreateGoalEdits(createResult = Result.success(debtGoal("new-goal")))
        val viewModel = CreateDebtGoalViewModel(reports, FakeCreateDebtActions(
            listResult = Result.success(listOf(debt("open-1", "open"))),
        ), writes = FakeDebtWriteActions())
        viewModel.reload()
        advanceUntilIdle()
        viewModel.toggleDebt("open-1")
        viewModel.updateName("还清欠款")
        viewModel.submit()
        advanceUntilIdle()
        assertEquals("new-goal", viewModel.state.value.createdPublicId)

        viewModel.consumeCreated()

        assertNull(viewModel.state.value.createdPublicId)
    }

    @Test
    fun canSubmitRequiresBothNameAndSelection() = runTest(dispatcher) {
        val viewModel = createViewModel(listOf(debt("open-1", "open")))
        viewModel.reload()
        advanceUntilIdle()

        assertFalse(viewModel.state.value.canSubmit)
        viewModel.updateName("还清欠款")
        assertFalse(viewModel.state.value.canSubmit) // name only
        viewModel.toggleDebt("open-1")
        assertTrue(viewModel.state.value.canSubmit) // name + selection
    }

    // ── fixtures ─────────────────────────────────────────────────────────────
    private fun createViewModel(candidates: List<Debt>): CreateDebtGoalViewModel =
        CreateDebtGoalViewModel(
            FakeCreateGoalEdits(),
            FakeCreateDebtActions(listResult = Result.success(candidates)),
            writes = FakeDebtWriteActions(),
        )

    private fun debt(publicId: String, status: String): Debt = Debt(
        publicId = publicId,
        ledgerId = "owner",
        direction = "i_owe",
        counterpartyType = "external",
        counterpartyAccountId = null,
        counterpartyLabel = "招商信用卡",
        principalAmountCents = 100000,
        remainingAmountCents = 40000,
        paidAmountCents = 60000,
        status = status,
        sourceType = "manual",
        sourceId = null,
        homeCurrencyCode = "CNY",
        originalCurrencyCode = null,
        originalAmountMinor = null,
        createdAt = "2026-06-13T00:00:00Z",
        updatedAt = "2026-06-15T00:00:00Z",
        rowVersion = 1L,
    )

    private fun debtGoal(publicId: String): Goal = Goal(
        publicId = publicId,
        ledgerId = "owner",
        name = "还清欠款",
        goalType = "debt_repayment",
        period = "monthly",
        month = "",
        category = null,
        targetAmountCents = 0,
        spentAmountCents = 0,
        remainingAmountCents = 0,
        progressPercent = 0,
        progressState = GoalProgressState.Idle,
        status = "active",
        createdAt = "2026-06-15T00:00:00Z",
        updatedAt = "2026-06-15T00:00:00Z",
        rowVersion = 1L,
        archivedAt = null,
        debtRepayment = null,
    )
}

internal data class CreateDebtGoalCall(val name: String, val debtPublicIds: List<String>)

internal class FakeCreateDebtActions(
    private val canModify: Boolean = true,
    var listResult: Result<List<Debt>> = Result.success(emptyList()),
) : DebtActions {
    val denials = MutableSharedFlow<SnapshotAccessDenial>()
    val resourceDenials = MutableSharedFlow<DebtReadResourceDenial>()
    var listGate: CompletableDeferred<Unit>? = null
    var fetchedAt = "2026-09-27T01:00:00Z"
    var fromCache = false
    override fun observeReadAccessDenials() = denials
    override fun observeResourceDenials() = resourceDenials
    override fun canModifyLedger(): Boolean = canModify
    override suspend fun listDebts(lens: com.ticketbox.domain.model.DebtListLens): Result<ReadSnapshot<DebtListPage>> {
        val captured = listResult.map { ReadSnapshot(DebtListPage(it, null), fetchedAt, fromCache) }
        listGate?.await()
        return captured
    }
    override suspend fun getDebt(publicId: String): Result<ReadSnapshot<Debt>> =
        Result.failure(UnsupportedOperationException())
    override suspend fun parseDebtBillImage(
        expectedBinding: LogicalSessionBinding,
        fileName: String,
        contentType: String?,
        bytes: ByteArray,
    ): Result<DebtBillSuggestion> = Result.failure(UnsupportedOperationException())

    // slice 8c widened DebtActions; the create-debt-goal flow only reads listDebts for the picker.


    override suspend fun setDebtKind(
        publicId: String,
        expectedRowVersion: Long,
        debtKind: String,
    ): Result<Debt> = Result.failure(UnsupportedOperationException())
}
