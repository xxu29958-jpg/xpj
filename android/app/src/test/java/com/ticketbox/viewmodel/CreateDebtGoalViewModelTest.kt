package com.ticketbox.viewmodel

import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtDraft
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardCards
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalProgressState
import com.ticketbox.domain.model.GoalUpdate
import com.ticketbox.domain.model.ReportsOverview
import com.ticketbox.domain.model.ReportsOverviewQuery
import kotlinx.coroutines.Dispatchers
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
    fun reloadLoadsOnlyOpenDebtsAndReflectsRole() = runTest(dispatcher) {
        val debts = FakeCreateDebtActions(
            canModify = false,
            listResult = Result.success(
                listOf(debt("open-1", "open"), debt("cleared-1", "cleared"), debt("voided-1", "voided")),
            ),
        )
        val viewModel = CreateDebtGoalViewModel(FakeCreateReportsActions(canModify = false), debts)
        viewModel.reload()
        advanceUntilIdle()

        // The picker tracks only OPEN debts (cleared → instant achieve, voided → review dead-end).
        assertEquals(listOf("open-1"), viewModel.state.value.candidates.map { it.publicId })
        assertFalse(viewModel.state.value.canModify)
        assertFalse(viewModel.state.value.isLoadingDebts)
    }

    @Test
    fun reloadFailureSetsLoadError() = runTest(dispatcher) {
        val debts = FakeCreateDebtActions(listResult = Result.failure(RuntimeException("offline")))
        val viewModel = CreateDebtGoalViewModel(FakeCreateReportsActions(), debts)
        viewModel.reload()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.candidates.isEmpty())
        assertTrue(viewModel.state.value.loadError != null)
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
        val reports = FakeCreateReportsActions()
        val viewModel = CreateDebtGoalViewModel(reports, FakeCreateDebtActions(
            listResult = Result.success(listOf(debt("open-1", "open"))),
        ))
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
        val reports = FakeCreateReportsActions()
        val viewModel = CreateDebtGoalViewModel(reports, FakeCreateDebtActions(
            listResult = Result.success(listOf(debt("open-1", "open"))),
        ))
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
        val reports = FakeCreateReportsActions(createResult = Result.success(debtGoal("new-goal")))
        val viewModel = CreateDebtGoalViewModel(reports, FakeCreateDebtActions(
            listResult = Result.success(
                listOf(debt("open-a", "open"), debt("open-b", "open"), debt("open-c", "open")),
            ),
        ))
        viewModel.reload()
        advanceUntilIdle()
        // Select out of candidate order; submit must still send candidate order.
        viewModel.toggleDebt("open-c")
        viewModel.toggleDebt("open-a")
        viewModel.updateName("  还清欠款  ")

        viewModel.submit()
        advanceUntilIdle()

        val call = reports.createDebtGoalCalls.single()
        assertEquals("还清欠款", call.name)
        assertEquals(listOf("open-a", "open-c"), call.debtPublicIds)
        assertEquals("new-goal", viewModel.state.value.createdPublicId)
        assertFalse(viewModel.state.value.isSubmitting)
    }

    @Test
    fun submitFailureSetsFormErrorAndClearsSubmitting() = runTest(dispatcher) {
        val reports = FakeCreateReportsActions(createResult = Result.failure(RuntimeException("conflict")))
        val viewModel = CreateDebtGoalViewModel(reports, FakeCreateDebtActions(
            listResult = Result.success(listOf(debt("open-1", "open"))),
        ))
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
        val reports = FakeCreateReportsActions(createResult = Result.success(debtGoal("new-goal")))
        val viewModel = CreateDebtGoalViewModel(reports, FakeCreateDebtActions(
            listResult = Result.success(listOf(debt("open-1", "open"))),
        ))
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
            FakeCreateReportsActions(),
            FakeCreateDebtActions(listResult = Result.success(candidates)),
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

private data class CreateDebtGoalCall(val name: String, val debtPublicIds: List<String>)

private class FakeCreateDebtActions(
    private val canModify: Boolean = true,
    private val listResult: Result<List<Debt>> = Result.success(emptyList()),
) : DebtActions {
    override fun canModifyLedger(): Boolean = canModify
    override suspend fun listDebts(): Result<List<Debt>> = listResult
    override suspend fun getDebt(publicId: String): Result<Debt> =
        Result.failure(UnsupportedOperationException())
    override suspend fun createDebt(draft: DebtDraft): Result<Debt> =
        Result.failure(UnsupportedOperationException())

    // slice 8c widened DebtActions; the create-debt-goal flow only reads listDebts for the picker.
    override suspend fun recordRepayment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
    ): Result<Debt> = Result.failure(UnsupportedOperationException())

    override suspend fun recordAdjustment(
        publicId: String,
        expectedRowVersion: Long,
        amountCents: Long,
        reason: String,
    ): Result<Debt> = Result.failure(UnsupportedOperationException())

    override suspend fun voidDebt(
        publicId: String,
        expectedRowVersion: Long,
        reason: String,
    ): Result<Debt> = Result.failure(UnsupportedOperationException())
}

private class FakeCreateReportsActions(
    private val canModify: Boolean = true,
    private val createResult: Result<Goal> = Result.failure(UnsupportedOperationException()),
) : ReportsActions {
    val createDebtGoalCalls = mutableListOf<CreateDebtGoalCall>()

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun createDebtGoal(name: String, debtPublicIds: List<String>): Result<Goal> {
        createDebtGoalCalls += CreateDebtGoalCall(name, debtPublicIds)
        return createResult
    }

    // ── unused ReportsActions surface ────────────────────────────────────────
    override suspend fun reportsOverview(query: ReportsOverviewQuery): Result<ReportsOverview> =
        Result.failure(UnsupportedOperationException())

    override suspend fun exportReportsOverviewCsv(query: ReportsOverviewQuery): Result<CsvExport> =
        Result.failure(UnsupportedOperationException())

    override suspend fun goals(month: String?, includeArchived: Boolean): Result<List<Goal>> =
        Result.success(emptyList())

    override suspend fun createGoal(draft: GoalDraft): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun goal(publicId: String): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun updateGoal(publicId: String, update: GoalUpdate): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun archiveGoal(publicId: String): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun debtGoals(includeArchived: Boolean): Result<List<Goal>> =
        Result.success(emptyList())

    override suspend fun replaceDebtLinks(
        publicId: String,
        expectedRowVersion: Long,
        debtPublicIds: List<String>,
    ): Result<Goal> = Result.failure(UnsupportedOperationException())

    override suspend fun acknowledgeDebtIntegrityReview(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<Goal> = Result.failure(UnsupportedOperationException())

    override suspend fun setDebtGoalTargetDate(
        publicId: String,
        expectedRowVersion: Long,
        targetDate: String?,
    ): Result<Goal> = Result.failure(UnsupportedOperationException())

    override suspend fun dashboardCards(surface: DashboardSurface): Result<DashboardCards> =
        Result.failure(UnsupportedOperationException())

    override suspend fun updateDashboardCards(
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface,
    ): Result<DashboardCards> = Result.failure(UnsupportedOperationException())
}
