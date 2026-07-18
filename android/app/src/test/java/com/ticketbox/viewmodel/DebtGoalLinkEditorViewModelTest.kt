package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtGoalLink
import com.ticketbox.domain.model.DebtRepaymentEvaluation
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class DebtGoalLinkEditorViewModelTest {
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
    fun loadsOpenCandidatesAndPreselectsExistingNonVoidedLinks() = runTest(dispatcher) {
        val goal = debtGoal(
            links = listOf(link("debt-a", "open"), link("debt-c", "cleared"), link("debt-b", "voided")),
            voidedIds = listOf("debt-b"),
        )
        val viewModel = viewModel(
            goal = goal,
            debts = listOf(
                linkEditorDebt("debt-a", "open"),
                linkEditorDebt("debt-b", "voided"),
                linkEditorDebt("debt-c", "cleared"),
                linkEditorDebt("debt-new", "open"),
                linkEditorDebt("unlinked-cleared", "cleared"),
            ),
        )

        viewModel.linkEditor.open()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.linkEditorOpen)
        assertEquals(
            listOf("debt-a", "debt-c", "debt-new"),
            viewModel.state.value.linkCandidates.map(Debt::publicId),
        )
        assertEquals(setOf("debt-a", "debt-c"), viewModel.state.value.selectedDebtIds)
    }

    @Test
    fun replaceUsesCurrentOccAndCandidateOrder() = runTest(dispatcher) {
        val goal = debtGoal(rowVersion = 7L, links = listOf(link("debt-a", "open")))
        val updated = debtGoal(rowVersion = 8L, links = listOf(link("debt-new", "open")))
        val reports = reports(goal, replaceResult = Result.success(updated))
        val viewModel = viewModel(
            goal = goal,
            debts = listOf(linkEditorDebt("debt-a", "open"), linkEditorDebt("debt-new", "open")),
            reports = reports,
        )
        viewModel.linkEditor.open()
        advanceUntilIdle()
        viewModel.linkEditor.toggle("debt-new")
        viewModel.linkEditor.toggle("debt-a")

        viewModel.linkEditor.save()
        advanceUntilIdle()

        assertEquals(
            ReplaceCall("debt-goal-1", 7L, listOf("debt-new")),
            reports.replaceCalls.single(),
        )
        assertEquals(8L, viewModel.state.value.selectedGoal?.rowVersion)
        assertTrue(!viewModel.state.value.linkEditorOpen)
    }

    @Test
    fun refusesToRemoveTheLastDebt() = runTest(dispatcher) {
        val goal = debtGoal(links = listOf(link("debt-a", "open")))
        val reports = reports(goal)
        val viewModel = viewModel(goal, listOf(linkEditorDebt("debt-a", "open")), reports)
        viewModel.linkEditor.open()
        advanceUntilIdle()

        viewModel.linkEditor.toggle("debt-a")

        assertEquals(setOf("debt-a"), viewModel.state.value.selectedDebtIds)
        assertNotNull(viewModel.state.value.error)
        assertTrue(reports.replaceCalls.isEmpty())
    }

    @Test
    fun failureKeepsDraftSelectionAndFeedback() = runTest(dispatcher) {
        val goal = debtGoal(links = listOf(link("debt-a", "open")))
        val reports = reports(goal, Result.failure(RuntimeException("conflict")))
        val viewModel = viewModel(
            goal,
            listOf(linkEditorDebt("debt-a", "open"), linkEditorDebt("debt-new", "open")),
            reports,
        )
        viewModel.linkEditor.open()
        advanceUntilIdle()
        viewModel.linkEditor.toggle("debt-new")

        viewModel.linkEditor.save()
        advanceUntilIdle()

        assertTrue(viewModel.state.value.linkEditorOpen)
        assertEquals(setOf("debt-a", "debt-new"), viewModel.state.value.selectedDebtIds)
        assertNotNull(viewModel.state.value.error)
        assertTrue(!viewModel.state.value.isSubmitting)
    }

    @Test
    fun viewerCannotOpenEditor() = runTest(dispatcher) {
        val goal = debtGoal(links = listOf(link("debt-a", "open")))
        val reports = reports(goal, canModify = false)
        val viewModel = viewModel(goal, listOf(linkEditorDebt("debt-a", "open")), reports)

        viewModel.linkEditor.open()
        advanceUntilIdle()

        assertTrue(!viewModel.state.value.linkEditorOpen)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class DebtGoalLinkEditorRaceTest {
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
    fun lateSuccessFromClosedGoalCannotReplaceNewGoalDraft() = runTest(dispatcher) {
        val goalA = debtGoal(publicId = "goal-a", links = listOf(link("debt-a", "open")))
        val goalB = debtGoal(publicId = "goal-b", links = listOf(link("debt-b", "open")))
        val reports = reports(goalA)
        val saveA = CompletableDeferred<Result<Goal>>()
        reports.replaceGates.add(saveA)
        reports.goalResultsByPublicId["goal-b"] = Result.success(goalB)
        val viewModel = viewModel(
            goal = goalA,
            debts = listOf(linkEditorDebt("debt-a", "open"), linkEditorDebt("debt-b", "open")),
            reports = reports,
        )
        viewModel.linkEditor.open()
        advanceUntilIdle()
        viewModel.linkEditor.save()
        runCurrent()
        assertTrue(viewModel.state.value.isSubmitting)

        viewModel.openDetail(goalB)
        advanceUntilIdle()
        viewModel.linkEditor.open()
        advanceUntilIdle()
        val goalBDraft = viewModel.state.value.selectedDebtIds
        saveA.complete(Result.success(goalA.copy(rowVersion = 4L)))
        advanceUntilIdle()

        assertEquals("goal-b", viewModel.state.value.selectedGoal?.publicId)
        assertEquals(goalBDraft, viewModel.state.value.selectedDebtIds)
        assertTrue(viewModel.state.value.linkEditorOpen)
        assertTrue(!viewModel.state.value.isSubmitting)
    }

    @Test
    fun lateFailureFromOldGoalCannotClearNewGoalSubmission() = runTest(dispatcher) {
        val goalA = debtGoal(publicId = "goal-a", links = listOf(link("debt-a", "open")))
        val goalB = debtGoal(publicId = "goal-b", links = listOf(link("debt-b", "open")))
        val reports = reports(goalA)
        val saveA = CompletableDeferred<Result<Goal>>()
        val saveB = CompletableDeferred<Result<Goal>>()
        reports.replaceGates.add(saveA)
        reports.replaceGates.add(saveB)
        reports.goalResultsByPublicId["goal-b"] = Result.success(goalB)
        val viewModel = viewModel(
            goal = goalA,
            debts = listOf(linkEditorDebt("debt-a", "open"), linkEditorDebt("debt-b", "open")),
            reports = reports,
        )
        viewModel.linkEditor.open()
        advanceUntilIdle()
        viewModel.linkEditor.save()
        runCurrent()
        viewModel.openDetail(goalB)
        advanceUntilIdle()
        viewModel.linkEditor.open()
        advanceUntilIdle()
        viewModel.linkEditor.save()
        runCurrent()

        saveA.complete(Result.failure(RuntimeException("late A failure")))
        runCurrent()

        assertEquals("goal-b", viewModel.state.value.selectedGoal?.publicId)
        assertTrue(viewModel.state.value.linkEditorOpen)
        assertTrue(viewModel.state.value.isSubmitting)
        assertEquals(null, viewModel.state.value.error)

        saveB.complete(Result.success(goalB.copy(rowVersion = 4L)))
        advanceUntilIdle()
        assertTrue(!viewModel.state.value.isSubmitting)
    }

    @Test
    fun conflictRefreshesOccAndPreservesDraftBeforeRetry() = runTest(dispatcher) {
        val goalV7 = debtGoal(rowVersion = 7L, links = listOf(link("debt-a", "open")))
        val goalV8 = goalV7.copy(rowVersion = 8L)
        val goalV9 = goalV7.copy(rowVersion = 9L, debtRepayment = goalV7.debtRepayment)
        val reports = reports(goalV7)
        val viewModel = viewModel(
            goal = goalV7,
            debts = listOf(linkEditorDebt("debt-a", "open"), linkEditorDebt("debt-new", "open")),
            reports = reports,
        )
        viewModel.linkEditor.open()
        advanceUntilIdle()
        viewModel.linkEditor.toggle("debt-new")
        val draft = viewModel.state.value.selectedDebtIds
        reports.goalResultsByPublicId[goalV7.publicId] = Result.success(goalV8)
        reports.queuedReplaceResults.add(
            Result.failure(RepositoryException("conflict", errorCode = "state_conflict")),
        )
        reports.queuedReplaceResults.add(Result.success(goalV9))

        viewModel.linkEditor.save()
        advanceUntilIdle()

        assertEquals(7L, reports.replaceCalls.single().expectedRowVersion)
        assertEquals(8L, viewModel.state.value.selectedGoal?.rowVersion)
        assertEquals(draft, viewModel.state.value.selectedDebtIds)
        assertTrue(viewModel.state.value.isLinkEditorSnapshotFresh)
        assertNotNull(viewModel.state.value.error)

        viewModel.linkEditor.save()
        advanceUntilIdle()
        assertEquals(8L, reports.replaceCalls.last().expectedRowVersion)
        assertEquals(9L, viewModel.state.value.selectedGoal?.rowVersion)
        assertTrue(!viewModel.state.value.linkEditorOpen)
    }

    @Test
    fun explicitRefreshRebasesDraftOntoLatestOcc() = runTest(dispatcher) {
        val goalV7 = debtGoal(rowVersion = 7L, links = listOf(link("debt-a", "open")))
        val goalV8 = goalV7.copy(rowVersion = 8L)
        val reports = reports(goalV7, replaceResult = Result.success(goalV8.copy(rowVersion = 9L)))
        val viewModel = viewModel(
            goal = goalV7,
            debts = listOf(linkEditorDebt("debt-a", "open"), linkEditorDebt("debt-new", "open")),
            reports = reports,
        )
        viewModel.linkEditor.open()
        advanceUntilIdle()
        viewModel.linkEditor.toggle("debt-new")
        val draft = viewModel.state.value.selectedDebtIds
        reports.goalResultsByPublicId[goalV7.publicId] = Result.success(goalV8)

        viewModel.linkEditor.refresh()
        advanceUntilIdle()
        viewModel.linkEditor.save()
        advanceUntilIdle()

        assertEquals(draft, reports.replaceCalls.single().debtPublicIds.toSet())
        assertEquals(8L, reports.replaceCalls.single().expectedRowVersion)
    }

    @Test
    fun lateOpenDetailFetchRebasesActiveDraftBeforeSave() = runTest(dispatcher) {
        val goalV7 = debtGoal(rowVersion = 7L, links = listOf(link("debt-a", "open")))
        val goalV8 = goalV7.copy(rowVersion = 8L)
        val reports = reports(goalV7, replaceResult = Result.success(goalV8.copy(rowVersion = 9L)))
        val openDetailGate = CompletableDeferred<Result<Goal>>()
        reports.goalGates.add(openDetailGate)
        reports.goalGates.add(CompletableDeferred(Result.success(goalV7)))
        reports.goalGates.add(CompletableDeferred(Result.success(goalV8)))
        val viewModel = viewModel(
            goal = goalV7,
            debts = listOf(linkEditorDebt("debt-a", "open"), linkEditorDebt("debt-new", "open")),
            reports = reports,
        )
        viewModel.linkEditor.open()
        advanceUntilIdle()
        viewModel.linkEditor.toggle("debt-new")
        val draft = viewModel.state.value.selectedDebtIds
        assertEquals(7L, viewModel.state.value.linkEditorSnapshotRowVersion)

        openDetailGate.complete(Result.success(goalV8))
        advanceUntilIdle()

        assertEquals(8L, viewModel.state.value.selectedGoal?.rowVersion)
        assertEquals(8L, viewModel.state.value.linkEditorSnapshotRowVersion)
        assertEquals(draft, viewModel.state.value.selectedDebtIds)
        viewModel.linkEditor.save()
        advanceUntilIdle()
        assertEquals(8L, reports.replaceCalls.single().expectedRowVersion)
    }

    @Test
    fun successfulSaveRemainsAuthoritativeWhenDetailRefreshLandsInFlight() = runTest(dispatcher) {
        val goalV7 = debtGoal(rowVersion = 7L, links = listOf(link("debt-a", "open")))
        val goalV8 = goalV7.copy(rowVersion = 8L)
        val goalV9 = goalV7.copy(rowVersion = 9L)
        val reports = reports(goalV7)
        val openDetailGate = CompletableDeferred<Result<Goal>>()
        val saveGate = CompletableDeferred<Result<Goal>>()
        reports.goalGates.add(openDetailGate)
        reports.goalGates.add(CompletableDeferred(Result.success(goalV7)))
        reports.replaceGates.add(saveGate)
        val viewModel = viewModel(
            goal = goalV7,
            debts = listOf(
                linkEditorDebt("debt-a", "open"),
                linkEditorDebt("debt-new", "open"),
            ),
            reports = reports,
        )
        viewModel.linkEditor.open()
        advanceUntilIdle()
        viewModel.linkEditor.save()
        runCurrent()
        viewModel.linkEditor.toggle("debt-new")
        viewModel.linkEditor.refresh()
        runCurrent()
        assertEquals(setOf("debt-a"), viewModel.state.value.selectedDebtIds)
        assertTrue(viewModel.state.value.isSubmitting)
        viewModel.linkEditor.close()
        assertTrue(viewModel.state.value.linkEditorOpen)
        assertTrue(viewModel.state.value.isSubmitting)

        openDetailGate.complete(Result.success(goalV8))
        runCurrent()
        assertEquals(8L, viewModel.state.value.selectedGoal?.rowVersion)
        assertTrue(viewModel.state.value.isSubmitting)

        saveGate.complete(Result.success(goalV9))
        advanceUntilIdle()
        assertEquals(9L, viewModel.state.value.selectedGoal?.rowVersion)
        assertTrue(!viewModel.state.value.linkEditorOpen)
        assertTrue(!viewModel.state.value.isSubmitting)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
private suspend fun TestScope.viewModel(
        goal: Goal,
        debts: List<Debt>,
        reports: FakeReportsActions = reports(goal),
    ): DebtGoalViewModel {
        val viewModel = DebtGoalViewModel(
            repository = reports,
            debts = FakeDebtGoalDebtActions(Result.success(debts)),
        )
        advanceUntilIdle()
        viewModel.openDetail(goal)
        advanceUntilIdle()
        return viewModel
    }

    private fun reports(
        goal: Goal,
        replaceResult: Result<Goal> = Result.failure(UnsupportedOperationException()),
        canModify: Boolean = true,
    ): FakeReportsActions = FakeReportsActions(
        canModify = canModify,
        debtGoalsResult = Result.success(listOf(goal)),
        goalResult = Result.success(goal),
        replaceResult = replaceResult,
    )

    private fun debtGoal(
        publicId: String = "debt-goal-1",
        rowVersion: Long = 3L,
        links: List<DebtGoalLink>,
        voidedIds: List<String> = emptyList(),
    ): Goal = Goal(
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
        createdAt = "2026-06-13T00:00:00Z",
        updatedAt = "2026-06-15T00:00:00Z",
        rowVersion = rowVersion,
        archivedAt = null,
        debtRepayment = DebtRepaymentEvaluation(
            goalVersion = 2,
            evaluationState = "in_progress",
            needsReview = false,
            achievedAt = null,
            achievedVersion = null,
            linkedDebts = links,
            voidedDebtPublicIds = voidedIds,
        ),
    )

    private fun link(publicId: String, status: String): DebtGoalLink = DebtGoalLink(
        debtPublicId = publicId,
        status = status,
        direction = "i_owe",
        counterpartyType = "external",
        counterpartyLabel = publicId,
        principalAmountCents = 100_000,
        remainingAmountCents = if (status == "cleared") 0 else 40_000,
        homeCurrencyCode = "CNY",
    )

private fun linkEditorDebt(publicId: String, status: String): Debt = Debt(
    publicId = publicId,
    ledgerId = "owner",
    direction = "i_owe",
    counterpartyType = "external",
    counterpartyAccountId = null,
    counterpartyLabel = publicId,
    principalAmountCents = 100_000,
    remainingAmountCents = if (status == "cleared") 0 else 40_000,
    paidAmountCents = if (status == "cleared") 100_000 else 60_000,
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
