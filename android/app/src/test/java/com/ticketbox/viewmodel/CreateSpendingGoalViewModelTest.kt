package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.domain.model.CurrencyCode
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.cancel
import kotlinx.coroutines.withContext
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
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class CreateSpendingGoalViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val models = mutableListOf<CreateSpendingGoalViewModel>()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun close() { models.forEach { it.viewModelScope.cancel() }; Dispatchers.resetMain() }
    private fun model(reports: RecordingSpendingGoalActions, edits: RecordingGoalEdits) =
        CreateSpendingGoalViewModel(reports, edits).also { models += it }

    @Test fun jpyCreateUsesCapabilityAndPreservesReenteredDraft() = runTest(dispatcher) {
        val reports = RecordingSpendingGoalActions()
        val edits = RecordingGoalEdits().apply { currencyResult = Result.success(CurrencyCode.JPY) }
        val vm = model(reports, edits)
        vm.reset("2026-09"); advanceUntilIdle()
        vm.updateName("餐饮"); vm.updateTargetAmount("1200")
        vm.reset("2026-09")
        assertEquals("1200", vm.state.value.targetAmountInput)
        vm.submit(); advanceUntilIdle()
        assertEquals(1200, reports.createCalls.single().targetAmountCents)
        assertEquals("2026-09", reports.createCalls.single().month)
        assertEquals("goal-1", vm.state.value.createdPublicId)
        vm.consumeCreated()
        assertEquals("", vm.state.value.name)
    }

    @Test fun duplicateSubmitAndLiveReadonlyRoleCannotCreateTwice() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val reports = RecordingSpendingGoalActions().apply { createGate = { gate.await() } }
        val edits = RecordingGoalEdits()
        val vm = model(reports, edits)
        advanceUntilIdle(); vm.updateName("餐饮"); vm.updateTargetAmount("100")
        vm.submit(); vm.submit(); advanceUntilIdle()
        assertEquals(1, reports.createCalls.size)
        gate.complete(Unit); advanceUntilIdle(); vm.consumeCreated()
        edits.access.value = edits.access.value!!.copy(canModify = false)
        advanceUntilIdle(); vm.updateName("新目标"); vm.updateTargetAmount("200"); vm.submit(); advanceUntilIdle()
        assertFalse(vm.state.value.canSubmit)
        assertEquals(1, reports.createCalls.size)
    }

    @Test fun failedCurrencyHasRetryAndRejectsInvalidInput() = runTest(dispatcher) {
        val reports = RecordingSpendingGoalActions()
        val edits = RecordingGoalEdits().apply { currencyResult = Result.failure(IllegalStateException("offline")) }
        val vm = model(reports, edits)
        advanceUntilIdle(); vm.updateName("餐饮"); vm.updateTargetAmount("1200"); vm.submit()
        assertTrue(reports.createCalls.isEmpty())
        assertFalse(vm.state.value.canSubmit)
        edits.currencyResult = Result.success(CurrencyCode.JPY)
        vm.retryCurrency(); advanceUntilIdle()
        vm.updateTargetAmount("12.50"); vm.submit(); advanceUntilIdle()
        assertNotNull(vm.state.value.formError)
        assertTrue(reports.createCalls.isEmpty())
        vm.updateTargetAmount("1200")
        assertTrue(vm.state.value.canSubmit)
    }

    @Test fun oldCreateCompletionCannotNavigateTheReplacementBinding() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val reports = RecordingSpendingGoalActions().apply { createGate = { withContext(NonCancellable) { gate.await() } } }
        val edits = RecordingGoalEdits()
        val vm = model(reports, edits)
        advanceUntilIdle(); vm.updateName("旧目标"); vm.updateTargetAmount("100"); vm.submit(); advanceUntilIdle()
        edits.access.value = edits.access.value!!.let { it.copy(binding = it.binding.copy(sessionGeneration = "session-2")) }
        advanceUntilIdle(); vm.updateName("新草稿")
        gate.complete(Unit); advanceUntilIdle()
        assertNull(vm.state.value.createdPublicId)
        assertEquals("新草稿", vm.state.value.name)
        assertFalse(vm.state.value.isSubmitting)
    }
}
