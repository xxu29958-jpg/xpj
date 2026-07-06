package com.ticketbox.viewmodel

import com.ticketbox.data.repository.ReportsActions
import com.ticketbox.domain.model.Goal
import com.ticketbox.domain.model.GoalDraft
import com.ticketbox.domain.model.GoalProgressState
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
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
import kotlin.test.assertNotNull
import kotlin.test.assertTrue
import java.lang.reflect.Proxy

@OptIn(ExperimentalCoroutinesApi::class)
class CreateSpendingGoalViewModelTest {
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
    fun resetUsesRequestedMonthAndReflectsRole() = runTest(dispatcher) {
        val reports = RecordingSpendingReportsActions(canModify = false)
        val viewModel = CreateSpendingGoalViewModel(reports.actions)

        viewModel.reset("2026-07")

        assertEquals("2026-07", viewModel.state.value.month)
        assertFalse(viewModel.state.value.canModify)
        assertFalse(viewModel.state.value.canSubmit)
    }

    @Test
    fun submitValidationBlocksMissingAmountWithoutApiCall() = runTest(dispatcher) {
        val reports = RecordingSpendingReportsActions()
        val viewModel = CreateSpendingGoalViewModel(reports.actions)

        viewModel.updateName("本月外卖")
        viewModel.submit()
        advanceUntilIdle()

        assertTrue(reports.createGoalCalls.isEmpty())
        assertNotNull(viewModel.state.value.formError)
    }

    @Test
    fun submitSuccessPassesSpendingGoalDraftAndSetsCreatedSignal() = runTest(dispatcher) {
        val reports = RecordingSpendingReportsActions(createResult = Result.success(spendingGoal("goal-new")))
        val viewModel = CreateSpendingGoalViewModel(reports.actions)

        viewModel.reset("2026-07")
        viewModel.updateName("本月外卖")
        viewModel.updateTargetAmount("128.50")
        viewModel.updateCategory("餐饮")
        viewModel.submit()
        advanceUntilIdle()

        assertEquals(
            GoalDraft(
                name = "本月外卖",
                month = "2026-07",
                targetAmountCents = 12850,
                category = "餐饮",
            ),
            reports.createGoalCalls.single(),
        )
        assertEquals("goal-new", viewModel.state.value.createdPublicId)
    }

    private fun spendingGoal(publicId: String): Goal = Goal(
        publicId = publicId,
        ledgerId = "owner",
        name = "本月外卖",
        goalType = "spending_limit",
        period = "monthly",
        month = "2026-07",
        category = "餐饮",
        targetAmountCents = 12850,
        spentAmountCents = 0,
        remainingAmountCents = 12850,
        progressPercent = 0,
        progressState = GoalProgressState.Idle,
        status = "active",
        createdAt = "2026-07-06T00:00:00Z",
        updatedAt = "2026-07-06T00:00:00Z",
        rowVersion = 1L,
        archivedAt = null,
    )
}

private class RecordingSpendingReportsActions(
    private val canModify: Boolean = true,
    private val createResult: Result<Goal> = Result.failure(UnsupportedOperationException()),
) {
    val createGoalCalls = mutableListOf<GoalDraft>()
    val actions: ReportsActions = Proxy.newProxyInstance(
        ReportsActions::class.java.classLoader,
        arrayOf(ReportsActions::class.java),
    ) { _, method, args ->
        when (method.name) {
            "canModifyLedger" -> canModify
            "createGoal",
            method.name.takeIf { it.startsWith("createGoal-") },
            -> {
                createGoalCalls += args?.first() as GoalDraft
                createResult.getOrThrow()
            }
            "goals",
            "debtGoals",
            -> Result.success(emptyList<Goal>())
            "toString" -> "RecordingSpendingReportsActions"
            else -> Result.failure<Any>(UnsupportedOperationException(method.name))
        }
    } as ReportsActions
}
