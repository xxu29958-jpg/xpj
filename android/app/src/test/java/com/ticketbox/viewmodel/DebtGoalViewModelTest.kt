package com.ticketbox.viewmodel

import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.DashboardCardUpdate
import com.ticketbox.domain.model.DashboardCards
import com.ticketbox.domain.model.DashboardSurface
import com.ticketbox.domain.model.DebtGoalLink
import com.ticketbox.domain.model.DebtRepaymentEvaluation
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
import kotlin.test.assertNull
import kotlin.test.assertTrue

class DebtGoalViewModelTest {

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
    fun initLoadsDebtGoalsAndReflectsRole() = runTest(dispatcher) {
        val repo = FakeReportsActions(canModify = false, debtGoalsResult = Result.success(listOf(debtGoal())))
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()

        assertEquals(1, viewModel.state.value.goals.size)
        assertEquals(false, viewModel.state.value.canModify)
        assertEquals(false, viewModel.state.value.isLoading)
    }

    @Test
    fun refreshFailureSetsError() = runTest(dispatcher) {
        val repo = FakeReportsActions(debtGoalsResult = Result.failure(RuntimeException("offline")))
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()

        assertTrue(viewModel.state.value.goals.isEmpty())
        assertTrue(viewModel.state.value.error != null)
    }

    @Test
    fun openDetailSelectsThenRefetchesLatchedCopy() = runTest(dispatcher) {
        val listed = debtGoal(evaluationState = "in_progress")
        val latched = debtGoal(evaluationState = "achieved", needsReview = false)
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(listed)),
            goalResult = Result.success(latched),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()

        viewModel.openDetail(listed)
        advanceUntilIdle()

        assertEquals(listOf("debt-goal-1"), repo.goalCalls)
        // the writer GET latched achievement server-side — detail reflects the fresh copy.
        assertEquals("achieved", viewModel.state.value.selectedGoal?.debtRepayment?.evaluationState)
    }

    @Test
    fun closeDetailClearsSelection() = runTest(dispatcher) {
        val goal = debtGoal()
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(goal)),
            goalResult = Result.success(goal),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(goal)
        advanceUntilIdle()

        viewModel.closeDetail()

        assertNull(viewModel.state.value.selectedGoal)
    }

    @Test
    fun removeVoidedDebtsReplacesWithNonVoidedIdsAndGoalRowVersion() = runTest(dispatcher) {
        val goal = debtGoal(needsReview = true, rowVersion = 7L)
        val replaced = debtGoal(needsReview = false, links = listOf(openLink()), voidedIds = emptyList())
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(goal)),
            goalResult = Result.success(goal),
            replaceResult = Result.success(replaced),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(goal)
        advanceUntilIdle()

        viewModel.removeVoidedDebts()
        advanceUntilIdle()

        val call = repo.replaceCalls.single()
        assertEquals("debt-goal-1", call.publicId)
        assertEquals(7L, call.expectedRowVersion)
        // only the non-voided link survives the replacement set.
        assertEquals(listOf("debt-a"), call.debtPublicIds)
        assertTrue(viewModel.state.value.flashMessage != null)
        assertEquals(false, viewModel.state.value.selectedGoal?.debtRepayment?.needsReview)
    }

    @Test
    fun removeVoidedDebtsWithEverythingVoidedSetsErrorWithoutApiCall() = runTest(dispatcher) {
        // every link voided → no clean replacement set; the repo is never called.
        val goal = debtGoal(needsReview = true, links = listOf(voidedLink()), voidedIds = listOf("debt-b"))
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(goal)),
            goalResult = Result.success(goal),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(goal)
        advanceUntilIdle()

        viewModel.removeVoidedDebts()
        advanceUntilIdle()

        assertTrue(repo.replaceCalls.isEmpty())
        assertTrue(viewModel.state.value.error != null)
    }

    @Test
    fun acknowledgePassesGoalRowVersionAndFlashesOnSuccess() = runTest(dispatcher) {
        val goal = debtGoal(needsReview = true, rowVersion = 9L)
        val acked = debtGoal(needsReview = false)
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(goal)),
            goalResult = Result.success(goal),
            acknowledgeResult = Result.success(acked),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(goal)
        advanceUntilIdle()

        viewModel.acknowledge()
        advanceUntilIdle()

        val call = repo.acknowledgeCalls.single()
        assertEquals("debt-goal-1", call.first)
        assertEquals(9L, call.second)
        assertTrue(viewModel.state.value.flashMessage != null)
        assertEquals(false, viewModel.state.value.selectedGoal?.debtRepayment?.needsReview)
    }

    @Test
    fun reloadClearsSelectionAndReloadsGoals() = runTest(dispatcher) {
        val goal = debtGoal()
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(goal)),
            goalResult = Result.success(goal),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(goal)
        advanceUntilIdle()
        val callsBeforeReload = repo.debtGoalsCalls

        // ledger-isolation: a (re-)open clears any prior ledger's data, then reloads.
        viewModel.reload()
        advanceUntilIdle()

        assertNull(viewModel.state.value.selectedGoal)
        assertTrue(repo.debtGoalsCalls > callsBeforeReload)
        assertEquals(1, viewModel.state.value.goals.size)
    }

    @Test
    fun mutationFailureSetsErrorAndClearsSubmitting() = runTest(dispatcher) {
        val goal = debtGoal(needsReview = true)
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(goal)),
            goalResult = Result.success(goal),
            acknowledgeResult = Result.failure(RuntimeException("conflict")),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(goal)
        advanceUntilIdle()

        viewModel.acknowledge()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.error != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    // ── fixtures ─────────────────────────────────────────────────────────────
    private fun openLink(): DebtGoalLink = DebtGoalLink(
        debtPublicId = "debt-a",
        status = "open",
        direction = "i_owe",
        counterpartyType = "external",
        counterpartyLabel = "招商信用卡",
        principalAmountCents = 100000,
        remainingAmountCents = 40000,
        homeCurrencyCode = "CNY",
    )

    private fun voidedLink(): DebtGoalLink = DebtGoalLink(
        debtPublicId = "debt-b",
        status = "voided",
        direction = "owed_to_me",
        counterpartyType = "member",
        counterpartyLabel = "家人",
        principalAmountCents = 50000,
        remainingAmountCents = 50000,
        homeCurrencyCode = "CNY",
    )

    private fun debtGoal(
        evaluationState: String = "in_progress",
        needsReview: Boolean = false,
        rowVersion: Long = 3L,
        links: List<DebtGoalLink> = listOf(openLink(), voidedLink()),
        voidedIds: List<String> = listOf("debt-b"),
    ): Goal = Goal(
        publicId = "debt-goal-1",
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
        createdAt = "2026-06-13T00:00:00Z",
        updatedAt = "2026-06-15T00:00:00Z",
        rowVersion = rowVersion,
        archivedAt = null,
        debtRepayment = DebtRepaymentEvaluation(
            goalVersion = 2,
            evaluationState = evaluationState,
            needsReview = needsReview,
            achievedAt = null,
            achievedVersion = null,
            linkedDebts = links,
            voidedDebtPublicIds = voidedIds,
        ),
    )
}

private data class ReplaceCall(
    val publicId: String,
    val expectedRowVersion: Long,
    val debtPublicIds: List<String>,
)

private class FakeReportsActions(
    private val canModify: Boolean = true,
    private val debtGoalsResult: Result<List<Goal>> = Result.success(emptyList()),
    private val goalResult: Result<Goal> = Result.failure(UnsupportedOperationException()),
    private val replaceResult: Result<Goal> = Result.failure(UnsupportedOperationException()),
    private val acknowledgeResult: Result<Goal> = Result.failure(UnsupportedOperationException()),
) : ReportsActions {
    val goalCalls = mutableListOf<String>()
    val replaceCalls = mutableListOf<ReplaceCall>()
    val acknowledgeCalls = mutableListOf<Pair<String, Long>>()
    var debtGoalsCalls = 0

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun debtGoals(includeArchived: Boolean): Result<List<Goal>> {
        debtGoalsCalls += 1
        return debtGoalsResult
    }

    override suspend fun goal(publicId: String): Result<Goal> {
        goalCalls += publicId
        return goalResult
    }

    override suspend fun replaceDebtLinks(
        publicId: String,
        expectedRowVersion: Long,
        debtPublicIds: List<String>,
    ): Result<Goal> {
        replaceCalls += ReplaceCall(publicId, expectedRowVersion, debtPublicIds)
        return replaceResult
    }

    override suspend fun acknowledgeDebtIntegrityReview(
        publicId: String,
        expectedRowVersion: Long,
    ): Result<Goal> {
        acknowledgeCalls += publicId to expectedRowVersion
        return acknowledgeResult
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

    override suspend fun updateGoal(publicId: String, update: GoalUpdate): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun archiveGoal(publicId: String): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun dashboardCards(surface: DashboardSurface): Result<DashboardCards> =
        Result.failure(UnsupportedOperationException())

    override suspend fun updateDashboardCards(
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface,
    ): Result<DashboardCards> = Result.failure(UnsupportedOperationException())
}
