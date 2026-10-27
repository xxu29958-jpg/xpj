package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.MonthCalendarFixture
import com.ticketbox.data.repository.calendar
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.advanceUntilIdle
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class FinancialMonthPlanningTest {
    @Test fun rateReviewResumesTheOutboxMonthWhenNoDefaultCouldBeRead() = budgetTest {
        val repository = FakeBudgetActions(budget())
        val binding = repository.commands.authoritativeBinding
        val calendars = MonthCalendarFixture(binding)
        val vm = BudgetAdviceViewModel(repository, calendars = calendars)
        advanceUntilIdle()
        val request = com.ticketbox.domain.model.ExchangeRateRequest("USD", "CNY", "2024-02-05", "7.1", "manual", 0)
        val row = com.ticketbox.data.repository.OutboxRow(1, binding.serverUrl, binding.ledgerId, binding.ownerKey,
            com.ticketbox.data.local.PendingMutationType.SaveManualExchangeRate, "manual_rate:USD:CNY:2024-02-05", "{}", 0,
            com.ticketbox.data.local.PendingMutationStatus.Conflict, 0, "version_conflict", "2024-02-05", null, null, "original-rate")
        val pending = com.ticketbox.data.repository.PendingManualRateSubmission(row,
            com.ticketbox.data.repository.ManualRateSubmission(1, "2024-02", null, request), null)
        repository.rates.submissions.value = listOf(pending)
        advanceUntilIdle()
        assertEquals("", vm.uiState.value.month)
        vm.reviewRate(pending); advanceUntilIdle()
        assertEquals("2024-02", vm.uiState.value.month)
        assertNotNull(vm.uiState.value.rateEditor)
        vm.saveRate(); advanceUntilIdle()
        assertEquals("2024-02", repository.rates.writes.single().first)
        assertEquals(pending, repository.rates.submissions.value.single())
    }

    @Test fun anUnresolvedStoredMonthIsPreservedUntilExplicitConfirmation() = budgetTest {
        val edits = RecordingGoalEdits()
        val binding = requireNotNull(edits.currentAccess()).binding
        val saved = SavedStateHandle()
        val bindingJson = com.squareup.moshi.Moshi.Builder().build()
            .adapter(com.ticketbox.data.repository.LogicalSessionBinding::class.java).toJson(binding)
        saved["spending.goal.creation.drafts"] = """[{"binding":$bindingJson,"creationKey":"legacy",
            "month":"2024-02","monthReady":false,"name":"原草稿"}]"""
        val calendars = MonthCalendarFixture(binding, calendar(binding))
        val vm = CreateSpendingGoalViewModel(edits, calendars, saved)
        advanceUntilIdle()
        assertEquals("2024-02", vm.state.value.month)
        assertFalse(vm.state.value.monthReady)
        assertEquals("原草稿", vm.state.value.name)
        vm.selectMonth("2024-02"); advanceUntilIdle()
        assertTrue(vm.state.value.monthReady)
        assertEquals(0, calendars.refreshes)
    }

    @Test fun budgetRequiresAMonthAndRetainsTheExplicitDraftAcrossReopen() = budgetTest {
        val repository = FakeBudgetActions(budget())
        val calendars = MonthCalendarFixture(repository.commands.authoritativeBinding).apply {
            response = Result.failure(java.io.IOException("offline"))
        }
        val saved = SavedStateHandle()
        val vm = BudgetViewModel(repository, savedStateHandle = saved, calendars = calendars)
        advanceUntilIdle()
        val failure = assertNotNull(vm.uiState.value.loadError)
        vm.updateTotalAmount("200"); vm.save(); advanceUntilIdle()
        assertTrue(repository.loadedMonths.isEmpty())
        assertTrue(repository.commands.savedMonths.isEmpty())
        assertEquals("", vm.uiState.value.month)
        calendars.response = Result.success(null)
        vm.refresh(); advanceUntilIdle()
        assertNotEquals(failure, vm.uiState.value.loadError)
        vm.selectMonth("2024-02"); advanceUntilIdle()
        vm.updateTotalAmount("00200.00")
        vm.viewModelScope.cancel()
        val reopened = BudgetViewModel(repository, savedStateHandle = saved, calendars = calendars)
        advanceUntilIdle()
        assertEquals("2024-02", reopened.uiState.value.month)
        assertEquals("00200.00", reopened.uiState.value.form.totalAmount)
        assertEquals(2, calendars.refreshes)
        reopened.updateTotalAmount("200.00")
        reopened.save(); advanceUntilIdle()
        assertEquals(listOf("2024-02"), repository.commands.savedMonths)
    }

    @Test fun adviceCannotReadAnUnknownMonthAndResumesWithAnExplicitMonth() = budgetTest {
        val repository = FakeBudgetActions(budget())
        val calendars = MonthCalendarFixture(repository.commands.authoritativeBinding).apply {
            response = Result.failure(java.io.IOException("offline"))
        }
        val vm = BudgetAdviceViewModel(repository, calendars = calendars)
        advanceUntilIdle()
        assertNotNull(vm.uiState.value.inputsError)
        assertTrue(repository.inputs.months.isEmpty())
        vm.requestAdvice(); advanceUntilIdle()
        assertTrue(repository.adviceMonths.isEmpty())
        vm.selectMonth("2024-02"); advanceUntilIdle()
        assertEquals(listOf("2024-02"), repository.inputs.months)
        vm.refreshInputs(); advanceUntilIdle()
        assertEquals("2024-02", vm.uiState.value.month)
    }

    @Test fun spendingGoalListRequiresSelectionWhenCalendarIsUnsupported() = budgetTest {
        val reports = RecordingSpendingGoalActions()
        val edits = RecordingGoalEdits()
        val calendars = MonthCalendarFixture(requireNotNull(edits.currentAccess()).binding)
        val vm = SpendingGoalsViewModel(reports, edits, calendars = calendars)
        advanceUntilIdle()
        assertTrue(reports.goalsCalls.isEmpty())
        assertEquals(null, vm.monthForNewGoal)
        assertNotNull(vm.state.value.loadError)
        vm.selectMonth("2024-02"); advanceUntilIdle()
        assertEquals("2024-02", reports.goalsCalls.single().month)
        assertEquals("2024-02", vm.monthForNewGoal)
    }

    @Test fun creationWaitsForCalendarRecoveryWithoutLosingTypedInput() = budgetTest {
        val edits = RecordingGoalEdits()
        val binding = requireNotNull(edits.currentAccess()).binding
        val calendars = MonthCalendarFixture(binding).apply { response = Result.failure(java.io.IOException("offline")) }
        val vm = CreateSpendingGoalViewModel(edits, calendars)
        advanceUntilIdle()
        vm.updateName("旅行"); vm.updateTargetAmount("100"); vm.submit(); advanceUntilIdle()
        assertFalse(vm.state.value.monthReady)
        assertEquals("", vm.state.value.month)
        assertNotNull(vm.state.value.monthError)
        assertTrue(edits.createCalls.isEmpty())
        calendars.response = Result.success(calendar(binding))
        vm.resolveGoalTaskMonth(); advanceUntilIdle()
        assertTrue(vm.state.value.monthReady)
        assertEquals("旅行", vm.state.value.name)
        vm.selectMonth("2024-02")
        calendars.response = Result.failure(java.io.IOException("offline again"))
        vm.resolveGoalTaskMonth(); vm.submit(); advanceUntilIdle()
        assertEquals("2024-02", edits.createCalls.single().month)
    }
}
