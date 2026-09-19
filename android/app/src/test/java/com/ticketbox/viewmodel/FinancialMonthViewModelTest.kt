package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.MonthCalendarFixture
import com.ticketbox.data.repository.calendar
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class FinancialMonthViewModelTest {
    private val binding = LogicalSessionBinding("https://api.example.com", "owner", "owner", "session-owner", "binding-owner-owner")

    @Test fun budgetWaitsForRuleButLateRuleCannotMoveSelectedMonthOrSavedDraft() = budgetTest {
        val gate = CompletableDeferred<Unit>()
        val calendars = MonthCalendarFixture(binding).apply {
            this.gate = { gate.await() }
            response = Result.success(calendar(binding))
        }
        val fake = FakeBudgetActions(budget())
        val vm = BudgetViewModel(fake, calendars = calendars)
        runCurrent()
        assertEquals(emptyList(), fake.loadedMonths)
        vm.nextMonth()
        val selected = vm.uiState.value.month
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(listOf(selected), fake.loadedMonths)
        vm.updateTotalAmount("123")
        vm.refresh()
        advanceUntilIdle()
        assertEquals(selected, vm.uiState.value.month)
        assertEquals("123", vm.uiState.value.form.totalAmount)
        assertEquals(1, calendars.refreshes)

        val restored = BudgetViewModel(FakeBudgetActions(budget()), savedStateHandle = SavedStateHandle(mapOf("month" to "2025-03")), calendars = calendars)
        advanceUntilIdle()
        assertEquals("2025-03", restored.uiState.value.month)
        assertEquals(1, calendars.refreshes)
    }

    @Test fun replacementBindingAndLateOldRuleCannotOverwriteCurrentBudget() = budgetTest {
        val gate = CompletableDeferred<Unit>()
        val access = MutableStateFlow<LedgerAccessContext?>(LedgerAccessContext(binding, true))
        val calendars = MonthCalendarFixture(binding).apply { this.gate = { gate.await() } }
        val fake = FakeBudgetActions(budget(), activeAccessFlow = access)
        val vm = BudgetViewModel(fake, calendars = calendars)
        runCurrent()
        val replacement = binding.copy(bindingRevision = "replacement")
        calendars.binding = replacement
        calendars.rule = calendar(replacement)
        access.value = LedgerAccessContext(replacement, true)
        runCurrent()
        val accepted = vm.uiState.value
        assertEquals(replacement, accepted.binding)
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(accepted.month, vm.uiState.value.month)
        assertEquals(1, fake.loadedMonths.size)
    }

    @Test fun adviceAndGoalsCaptureBeforeQueryAndKeepUserSelectionDuringResolution() = budgetTest {
        val gate = CompletableDeferred<Unit>()
        val calendars = MonthCalendarFixture(binding).apply { this.gate = { gate.await() } }
        val fake = FakeBudgetActions(budget())
        val advice = BudgetAdviceViewModel(fake, calendars = calendars)
        runCurrent()
        assertTrue(fake.inputMonths.isEmpty())
        advice.shiftMonth(-2)
        val selected = advice.uiState.value.month
        gate.complete(Unit)
        advanceUntilIdle()
        assertEquals(listOf(selected), fake.inputMonths)
        advice.requestAdvice()
        advanceUntilIdle()
        assertEquals(listOf(selected), fake.adviceMonths)

        val edits = RecordingGoalEdits()
        val reports = RecordingSpendingGoalActions()
        val goalGate = CompletableDeferred<Unit>()
        calendars.binding = requireNotNull(edits.currentAccess()).binding
        calendars.gate = { goalGate.await() }
        val goals = SpendingGoalsViewModel(reports, edits, calendars = calendars)
        runCurrent()
        assertTrue(reports.goalsCalls.isEmpty())
        goals.previousMonth()
        val goalMonth = goals.state.value.month
        goalGate.complete(Unit)
        advanceUntilIdle()
        assertEquals(goalMonth, reports.goalsCalls.single().month)
    }

    @Test fun newGoalCanChooseMonthWhileRuleLoadsAndOriginalCreationKeepsItsBody() = budgetTest {
        val edits = RecordingGoalEdits()
        val gate = CompletableDeferred<Unit>()
        val calendars = MonthCalendarFixture(requireNotNull(edits.currentAccess()).binding).apply {
            this.gate = { gate.await() }
        }
        val create = CreateSpendingGoalViewModel(edits, calendars)
        runCurrent()
        create.updateName("Food")
        create.updateTargetAmount("100")
        create.shiftMonth(-3)
        val month = create.state.value.month
        create.submit()
        runCurrent()
        assertEquals(month, edits.createCalls.single().month)
        val original = create.state.value.pending
        gate.complete(Unit)
        advanceUntilIdle()
        create.reset("2030-12")
        assertEquals(month, create.state.value.month)
        assertEquals(original, create.state.value.pending)
        assertEquals(1, edits.createCalls.size)
    }
}
