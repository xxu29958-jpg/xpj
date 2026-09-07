package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.DebtGoalLink
import com.ticketbox.domain.model.DebtRepaymentEvaluation
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalProgressState
import java.lang.reflect.Proxy
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
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
import kotlin.test.assertNotNull
import kotlin.test.assertNull

class DebtGoalCanonicalContinuityTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun canonicalListReplacesTheWholeSelectedGoalWhenItsAdditionalDetailReadFails() = runTest(dispatcher) {
        val original = canonicalDebtGoal()
        var listed = original
        var detailFails = false
        var detailCalls = 0
        val unexpected = Proxy.newProxyInstance(ReportsActions::class.java.classLoader,
            arrayOf(ReportsActions::class.java)) { _, method, _ -> error("Unexpected goal call: ${method.name}") } as ReportsActions
        val repository = object : ReportsActions by unexpected {
            override fun canModifyLedger() = true
            override suspend fun debtGoals(includeArchived: Boolean) = Result.success(listOf(listed))
            override suspend fun goal(publicId: String): Result<Goal> {
                assertEquals(original.publicId, publicId)
                detailCalls++
                return if (detailFails) Result.failure(IllegalStateException("Synthetic failed detail read"))
                else Result.success(original)
            }
        }
        val viewModel = DebtGoalViewModel(repository, FakeDebtAdjustmentActions())
        try {
            advanceUntilIdle()
            viewModel.openDetail(original)
            advanceUntilIdle()
            assertEquals(original, viewModel.state.value.selectedGoal)
            val evaluation = requireNotNull(original.debtRepayment)
            listed = original.copy(name = "权威目标名称", rowVersion = 4, updatedAt = "2026-09-07T01:00:00Z",
                debtRepayment = evaluation.copy(linkedDebts = evaluation.linkedDebts.map {
                    it.copy(remainingAmountCents = 53_000)
                }))
            detailFails = true

            viewModel.refresh()
            advanceUntilIdle()

            assertEquals(2, detailCalls, "The existing additional detail producer really failed")
            assertEquals(listOf(listed), viewModel.state.value.goals)
            assertEquals(listed, viewModel.state.value.selectedGoal, "Preserve full canonical fields and OCC, not only amount")
            assertNotNull(viewModel.state.value.error)
        } finally {
            viewModel.viewModelScope.cancel()
        }
    }

    @OptIn(ExperimentalCoroutinesApi::class)
    @Test
    fun stoppedAdjustmentRequiresANewGoalQueryWithoutComparingGoalVersionToDebtOcc() = runTest(dispatcher) {
        val original = canonicalDebtGoal("debt-1")
        var current = original
        var result = Result.success(listOf(original))
        var gate: CompletableDeferred<Unit>? = null
        val unexpected = Proxy.newProxyInstance(ReportsActions::class.java.classLoader,
            arrayOf(ReportsActions::class.java)) { _, method, _ -> error("Unexpected goal call: ${method.name}") } as ReportsActions
        val repo = object : ReportsActions by unexpected {
            override fun canModifyLedger() = true
            override suspend fun debtGoals(includeArchived: Boolean): Result<List<Goal>> {
                val captured = result
                gate?.await()
                return captured
            }
            override suspend fun goal(publicId: String) = Result.success(current)
        }
        val adjustments = FakeDebtAdjustmentActions()
        val vm = DebtGoalViewModel(repo, adjustments)
        try {
            advanceUntilIdle()
            vm.openDetail(original)
            advanceUntilIdle()
            val oldRead = CompletableDeferred<Unit>()
            gate = oldRead
            vm.refresh()
            runCurrent()
            gate = null
            result = Result.failure(IllegalStateException("post-terminal goal query failed"))
            adjustments.rows.value = listOf(pendingAdjustment(status = PendingMutationStatus.Abandoned))
            advanceUntilIdle()
            assertNotNull(vm.state.value.error)
            oldRead.complete(Unit)
            advanceUntilIdle()
            assertNotNull(vm.state.value.error)
            assertEquals(original, vm.state.value.selectedGoal)
            current = original.copy(name = "终止重试后核对的目标")
            result = Result.success(listOf(current))
            vm.refresh()
            advanceUntilIdle()
            assertEquals(3L, current.rowVersion, "Goal version is independent of original Debt OCC 7")
            assertEquals(current, vm.state.value.selectedGoal)
            assertEquals(listOf(current), vm.state.value.goals)
            assertNull(vm.state.value.error)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }
}

private fun canonicalDebtGoal(debtPublicId: String = "debt-original") = Goal(
    publicId = "goal-original", ledgerId = "owner", name = "原目标名称", goalType = "debt_repayment",
    period = "monthly", month = "", category = null, targetAmountCents = 0, spentAmountCents = 0,
    remainingAmountCents = 0, progressPercent = 0, progressState = GoalProgressState.Idle, status = "active",
    createdAt = "2026-09-06T00:00:00Z", updatedAt = "2026-09-06T00:00:00Z", rowVersion = 3, archivedAt = null,
    debtRepayment = DebtRepaymentEvaluation(goalVersion = 2, evaluationState = "in_progress", needsReview = false,
        achievedAt = null, achievedVersion = null, linkedDebts = listOf(DebtGoalLink(
            debtPublicId = debtPublicId, status = "open", direction = "i_owe", counterpartyType = "external",
            counterpartyLabel = "原借款对象", principalAmountCents = 50_000, remainingAmountCents = 50_000,
            homeCurrencyCode = "CNY",
        )), voidedDebtPublicIds = emptyList()),
)
