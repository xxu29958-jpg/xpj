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
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import java.time.LocalDate
import java.time.ZoneOffset
import java.util.TimeZone
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
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

        assertTrue(repo.goalCalls.contains("debt-goal-1"))
        // the writer GET latched achievement server-side — detail reflects the fresh copy.
        assertEquals("achieved", viewModel.state.value.selectedGoal?.debtRepayment?.evaluationState)
    }

    @Test
    fun listRefreshRelatchesCompletedGoalsWithoutOpeningDetail() = runTest(dispatcher) {
        val listed = debtGoal(evaluationState = "in_progress", links = listOf(externalLink("open")))
        val latched = debtGoal(evaluationState = "achieved", links = listOf(externalLink("cleared")))
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(listed)),
            goalResult = Result.success(latched),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()

        assertEquals(listOf("debt-goal-1"), repo.goalCalls)
        assertNull(viewModel.state.value.selectedGoal)
        assertEquals("achieved", viewModel.state.value.goals.single().debtRepayment?.evaluationState)
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
    fun staleRefreshDoesNotRevertACommittedReview() = runTest(dispatcher) {
        val acked = debtGoal(needsReview = false)
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(debtGoal(needsReview = true))),
            goalResult = Result.success(debtGoal(needsReview = true)),
            acknowledgeResult = Result.success(acked),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(debtGoal(needsReview = true))
        advanceUntilIdle()

        // a slow refresh starts and stalls inside debtGoals()...
        val gate = CompletableDeferred<Unit>()
        repo.debtGoalsGate = gate
        viewModel.refresh()
        runCurrent()
        // ...then the user acknowledges (commits) while that refresh is still in flight.
        repo.debtGoalsGate = null
        viewModel.acknowledge()
        advanceUntilIdle()
        // release the now-stale refresh; its older snapshot must NOT revert the commit.
        gate.complete(Unit)
        advanceUntilIdle()

        assertEquals(false, viewModel.state.value.selectedGoal?.debtRepayment?.needsReview)
    }

    @Test
    fun refreshRelatchesOpenDetailViaDetailEndpoint() = runTest(dispatcher) {
        // the list path is read-only; an open detail must be re-latched via goal().
        val listSnapshot = debtGoal(evaluationState = "in_progress")
        val latchedDetail = debtGoal(evaluationState = "achieved")
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(listSnapshot)),
            goalResult = Result.success(latchedDetail),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(listSnapshot)
        advanceUntilIdle()
        val goalCallsBefore = repo.goalCalls.size

        viewModel.refresh()
        advanceUntilIdle()

        assertTrue(repo.goalCalls.size > goalCallsBefore)
        // selectedGoal came from the latching detail endpoint, not the in_progress list.
        assertEquals("achieved", viewModel.state.value.selectedGoal?.debtRepayment?.evaluationState)
    }

    @Test
    fun archiveSelectedClearsDetailAndReloads() = runTest(dispatcher) {
        val goal = debtGoal(needsReview = true)
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(goal)),
            goalResult = Result.success(goal),
            archiveResult = Result.success(debtGoal(needsReview = true)),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(goal)
        advanceUntilIdle()

        viewModel.archiveSelected()
        advanceUntilIdle()

        assertEquals(listOf("debt-goal-1"), repo.archiveCalls)
        assertNull(viewModel.state.value.selectedGoal)
        assertTrue(viewModel.state.value.flashMessage != null)
    }

    @Test
    fun supersededRefreshStillClearsLoadingFlag() = runTest(dispatcher) {
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(debtGoal())),
            goalResult = Result.success(debtGoal()),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()

        // a slow refresh stalls in debtGoals()...
        val gate = CompletableDeferred<Unit>()
        repo.debtGoalsGate = gate
        viewModel.refresh()
        runCurrent()
        assertTrue(viewModel.state.value.isLoading)
        // ...superseded by a non-refresh action (opening a detail) before it returns.
        repo.debtGoalsGate = null
        viewModel.openDetail(debtGoal())
        advanceUntilIdle()
        gate.complete(Unit)
        advanceUntilIdle()

        // the dropped refresh must not leave the screen stuck refreshing.
        assertEquals(false, viewModel.state.value.isLoading)
    }

    @Test
    fun refreshClearStaleClearsSelectionAndReloadsGoals() = runTest(dispatcher) {
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
        viewModel.refresh(clearStale = true)
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

    // ── ADR-0049 §7.0 / 8e-6c 还清日期 setter ──────────────────────────────────

    @Test
    fun setTargetDateSetsIsoDateWithGoalRowVersionAndFlashes() = runTest(dispatcher) {
        val goal = debtGoal(rowVersion = 4L)
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(goal)),
            goalResult = Result.success(goal),
        )
        repo.setTargetDateResult = Result.success(debtGoal(rowVersion = 5L))
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(goal)
        advanceUntilIdle()

        // The Material3 picker reports UTC-midnight millis; the VM renders it to ISO yyyy-MM-dd. Pin a
        // NEGATIVE-offset default tz around the conversion: epochMillisToIsoDate uses ZoneOffset.UTC, so a
        // regression to systemDefault() would render 2028-02-29 here and fail (tz off-by-one,
        // [[feedback_test_month_timezone_alignment]]).
        val millis = LocalDate.of(2028, 3, 1).atStartOfDay(ZoneOffset.UTC).toInstant().toEpochMilli()
        val previousTz = TimeZone.getDefault()
        TimeZone.setDefault(TimeZone.getTimeZone("America/New_York"))
        try {
            viewModel.setTargetDate(millis)
            advanceUntilIdle()
        } finally {
            TimeZone.setDefault(previousTz)
        }

        val call = repo.targetDateCalls.single()
        assertEquals("debt-goal-1", call.first)
        assertEquals(4L, call.second) // OCC carrier = the goal's row_version
        assertEquals("2028-03-01", call.third) // UTC millis → ISO date, no day-drift
        assertTrue(viewModel.state.value.flashMessage != null)
        assertEquals(false, viewModel.state.value.isSubmitting)
    }

    @Test
    fun setTargetDateClearPassesNullToTheRepository() = runTest(dispatcher) {
        val goal = debtGoal(rowVersion = 4L)
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(goal)),
            goalResult = Result.success(goal),
        )
        repo.setTargetDateResult = Result.success(debtGoal(rowVersion = 5L))
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(goal)
        advanceUntilIdle()

        // null epoch-millis = clear the deadline; the repo (and wire) carry a null target_date.
        viewModel.setTargetDate(null)
        advanceUntilIdle()

        val call = repo.targetDateCalls.single()
        assertEquals(4L, call.second)
        assertNull(call.third)
    }

    // ── ADR-0049 §6.6 计划达成撒花（边沿 / 成分 / 去重，达成只读服务端 evaluation_state）─────────────

    @Test
    fun memberPlanCompletionEmitsCelebration() = runTest(dispatcher) {
        // 详情停在 in_progress，再 fetch 到 achieved（纯成员）→ 浮层撒花信号；成员不走 flash。
        val listed = debtGoal(evaluationState = "in_progress", links = listOf(memberLink("open")), voidedIds = emptyList())
        val achieved = debtGoal(evaluationState = "achieved", links = listOf(memberLink("cleared")), voidedIds = emptyList())
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(listed)),
            goalResult = Result.success(achieved),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()

        viewModel.openDetail(listed)
        advanceUntilIdle()

        assertNotNull(viewModel.celebration.value)
        assertEquals("还清欠款", viewModel.celebration.value?.goalName)
        assertNull(viewModel.state.value.flashMessage)
    }

    @Test
    fun externalPlanCompletionFlashesWithoutMascotCelebration() = runTest(dispatcher) {
        // 纯外部计划达成 → 轻量 flash，不撒花、不夹夹（§6.7）。
        val listed = debtGoal(evaluationState = "in_progress", links = listOf(externalLink("open")), voidedIds = emptyList())
        val achieved = debtGoal(evaluationState = "achieved", links = listOf(externalLink("cleared")), voidedIds = emptyList())
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(listed)),
            goalResult = Result.success(achieved),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()

        viewModel.openDetail(listed)
        advanceUntilIdle()

        assertNull(viewModel.celebration.value)
        assertTrue(viewModel.state.value.flashMessage != null)
    }

    @Test
    fun mixedPlanCompletionFlashesWithoutMascotCelebration() = runTest(dispatcher) {
        // 混装（成员 + 外部）→ 中性 flash，不夹夹撒花（避免给信用卡撒花，§6.7）。
        val listed = debtGoal(
            evaluationState = "in_progress",
            links = listOf(memberLink("open"), externalLink("open")),
            voidedIds = emptyList(),
        )
        val achieved = debtGoal(
            evaluationState = "achieved",
            links = listOf(memberLink("cleared"), externalLink("cleared")),
            voidedIds = emptyList(),
        )
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(listed)),
            goalResult = Result.success(achieved),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()

        viewModel.openDetail(listed)
        advanceUntilIdle()

        assertNull(viewModel.celebration.value)
        assertTrue(viewModel.state.value.flashMessage != null)
    }

    @Test
    fun openingAnAlreadyAchievedPlanDoesNotCelebrate() = runTest(dispatcher) {
        // 首次打开一个早已达成的计划（list 拷贝已是 achieved）不撒花——避免历史达成误触（§6.6）。
        val achieved = debtGoal(evaluationState = "achieved", links = listOf(memberLink("cleared")), voidedIds = emptyList())
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(achieved)),
            goalResult = Result.success(achieved),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()

        viewModel.openDetail(achieved)
        advanceUntilIdle()

        assertNull(viewModel.celebration.value)
    }

    @Test
    fun planCompletionCelebratesOncePerGoalVersion() = runTest(dispatcher) {
        // 同一 goal_version 的达成只撒一次：消费后重新进入（list 仍 in_progress）不再撒（§6.6 去重）。
        val listed = debtGoal(evaluationState = "in_progress", links = listOf(memberLink("open")), voidedIds = emptyList())
        val achieved = debtGoal(evaluationState = "achieved", links = listOf(memberLink("cleared")), voidedIds = emptyList())
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(listed)),
            goalResult = Result.success(achieved),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()

        viewModel.openDetail(listed)
        advanceUntilIdle()
        assertNotNull(viewModel.celebration.value)
        viewModel.consumeCelebration()
        viewModel.closeDetail()

        viewModel.openDetail(listed)
        advanceUntilIdle()

        assertNull(viewModel.celebration.value)
    }

    @Test
    fun consumeCelebrationClearsTheSignal() = runTest(dispatcher) {
        val listed = debtGoal(evaluationState = "in_progress", links = listOf(memberLink("open")), voidedIds = emptyList())
        val achieved = debtGoal(evaluationState = "achieved", links = listOf(memberLink("cleared")), voidedIds = emptyList())
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(listed)),
            goalResult = Result.success(achieved),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(listed)
        advanceUntilIdle()
        assertNotNull(viewModel.celebration.value)

        viewModel.consumeCelebration()

        assertNull(viewModel.celebration.value)
    }

    @Test
    fun removeVoidedThatCompletesAMemberPlanCelebrates() = runTest(dispatcher) {
        // 移除作废欠款后新版本恰好全清（纯成员）→ 用户在该屏目击达成 → 撒花。
        val needsReview = debtGoal(
            evaluationState = "not_evaluable",
            needsReview = true,
            rowVersion = 5L,
            links = listOf(memberLink("cleared"), memberLink("voided", id = "m-voided")),
            voidedIds = listOf("m-voided"),
        )
        val completed = debtGoal(evaluationState = "achieved", links = listOf(memberLink("cleared")), voidedIds = emptyList())
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(needsReview)),
            goalResult = Result.success(needsReview),
            replaceResult = Result.success(completed),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(needsReview)
        advanceUntilIdle()

        viewModel.removeVoidedDebts()
        advanceUntilIdle()

        assertNotNull(viewModel.celebration.value)
    }

    @Test
    fun refreshThatLatchesAnOpenInProgressDetailToAchievedCelebrates() = runTest(dispatcher) {
        // 设计主路径（§6.6）：详情已打开停在 in_progress（openDetail 不跨边沿），随后一次 refresh 的 detail
        // 重拉翻成 achieved → latchSelectedDetail 处的撒花调用点跨边沿。直接钉死那条主路径（不经 openDetail）。
        val inProgress = debtGoal(evaluationState = "in_progress", links = listOf(memberLink("open")), voidedIds = emptyList())
        val achieved = debtGoal(evaluationState = "achieved", links = listOf(memberLink("cleared")), voidedIds = emptyList())
        val repo = FakeReportsActions(
            debtGoalsResult = Result.success(listOf(inProgress)),
            goalResult = Result.success(inProgress),
        )
        val viewModel = DebtGoalViewModel(repo)
        advanceUntilIdle()
        viewModel.openDetail(inProgress)
        advanceUntilIdle()
        assertNull(viewModel.celebration.value) // openDetail fetched in_progress → no edge yet

        // 详情打开期间最后一笔在别处被清，detail 重拉将翻 achieved。
        repo.goalResultOverride = Result.success(achieved)
        viewModel.refresh()
        advanceUntilIdle()

        assertNotNull(viewModel.celebration.value) // latchSelectedDetail in_progress→achieved 边沿撒花
    }

    // ── fixtures ─────────────────────────────────────────────────────────────
    private fun memberLink(status: String, id: String = "m-$status"): DebtGoalLink = DebtGoalLink(
        debtPublicId = id,
        status = status,
        direction = "i_owe",
        counterpartyType = "member",
        counterpartyLabel = "小明",
        principalAmountCents = 10000,
        remainingAmountCents = if (status == "cleared") 0 else 10000,
        homeCurrencyCode = "CNY",
    )

    private fun externalLink(status: String, id: String = "e-$status"): DebtGoalLink = DebtGoalLink(
        debtPublicId = id,
        status = status,
        direction = "i_owe",
        counterpartyType = "external",
        counterpartyLabel = "招商信用卡",
        principalAmountCents = 10000,
        remainingAmountCents = if (status == "cleared") 0 else 10000,
        homeCurrencyCode = "CNY",
    )

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
    private val archiveResult: Result<Goal> = Result.failure(UnsupportedOperationException()),
) : ReportsActions {
    val goalCalls = mutableListOf<String>()
    val replaceCalls = mutableListOf<ReplaceCall>()
    val acknowledgeCalls = mutableListOf<Pair<String, Long>>()
    val archiveCalls = mutableListOf<String>()
    val targetDateCalls = mutableListOf<Triple<String, Long, String?>>()
    var debtGoalsCalls = 0

    /** When set, debtGoals() stalls until completed — used to interleave a slow load. */
    var debtGoalsGate: CompletableDeferred<Unit>? = null

    /** When set, the NEXT (and subsequent) goal() return this instead of [goalResult] —
     * lets a test flip the detail re-fetch result between openDetail and a later refresh. */
    var goalResultOverride: Result<Goal>? = null

    /** The 8e-6c setDebtGoalTargetDate result — a var (not a ctor param) so the constructor stays
     * within the LongParameterList limit; tests set it before exercising the setter. */
    var setTargetDateResult: Result<Goal> = Result.failure(UnsupportedOperationException())

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun debtGoals(includeArchived: Boolean): Result<List<Goal>> {
        debtGoalsCalls += 1
        debtGoalsGate?.await()
        return debtGoalsResult
    }

    override suspend fun goal(publicId: String): Result<Goal> {
        goalCalls += publicId
        return goalResultOverride ?: goalResult
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

    override suspend fun setDebtGoalTargetDate(
        publicId: String,
        expectedRowVersion: Long,
        targetDate: String?,
    ): Result<Goal> {
        targetDateCalls += Triple(publicId, expectedRowVersion, targetDate)
        return setTargetDateResult
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

    override suspend fun createDebtGoal(name: String, debtPublicIds: List<String>): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun updateGoal(publicId: String, update: GoalUpdate): Result<Goal> =
        Result.failure(UnsupportedOperationException())

    override suspend fun archiveGoal(publicId: String): Result<Goal> {
        archiveCalls += publicId
        return archiveResult
    }

    override suspend fun dashboardCards(surface: DashboardSurface): Result<DashboardCards> =
        Result.failure(UnsupportedOperationException())

    override suspend fun updateDashboardCards(
        updates: List<DashboardCardUpdate>,
        surface: DashboardSurface,
    ): Result<DashboardCards> = Result.failure(UnsupportedOperationException())
}
