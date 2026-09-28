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
    private fun model(edits: RecordingGoalEdits) =
        CreateSpendingGoalViewModel(edits).also { models += it }

    @Test fun jpyCreateUsesCapabilityAndPreservesReenteredDraft() = runTest(dispatcher) {
        val edits = RecordingGoalEdits().apply { currencyResult = Result.success(CurrencyCode.JPY) }
        val vm = model(edits)
        vm.reset("2026-09"); advanceUntilIdle()
        vm.updateName("餐饮"); vm.updateTargetAmount("1200")
        vm.reset("2026-09")
        assertEquals("1200", vm.state.value.targetAmountInput)
        vm.submit(); advanceUntilIdle()
        assertEquals(1200, edits.createCalls.single().targetAmountCents)
        assertEquals("JPY", edits.createCalls.single().homeCurrencyCode)
        assertEquals("2026-09", edits.createCalls.single().month)
        assertNull(vm.state.value.createdPublicId)
        assertNotNull(vm.state.value.pending)
        assertFalse(vm.state.value.canSubmit)
        val accepted = edits.creations.value.single()
        edits.creations.value = listOf(accepted.copy(row = accepted.row.copy(status = com.ticketbox.data.local.PendingMutationStatus.Done),
            confirmed = spendingGoal().copy(homeCurrencyCode = "JPY", targetAmountCents = 1200)))
        advanceUntilIdle()
        assertEquals("goal-1", vm.state.value.createdPublicId)
        vm.consumeCreated()
        assertEquals("", vm.state.value.name)
    }

    @Test fun duplicateSubmitAndLiveReadonlyRoleCannotCreateTwice() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val edits = RecordingGoalEdits().apply { createGate = { gate.await() } }
        val vm = model(edits)
        advanceUntilIdle(); vm.updateName("餐饮"); vm.updateTargetAmount("100")
        vm.submit(); vm.submit(); advanceUntilIdle()
        assertEquals(1, edits.createCalls.size)
        gate.complete(Unit); advanceUntilIdle(); vm.consumeCreated()
        edits.access.value = edits.access.value!!.copy(canModify = false)
        advanceUntilIdle(); vm.updateName("新目标"); vm.updateTargetAmount("200"); vm.submit(); advanceUntilIdle()
        assertFalse(vm.state.value.canSubmit)
        assertEquals(1, edits.createCalls.size)
    }

    @Test fun failedCurrencyHasRetryAndRejectsInvalidInput() = runTest(dispatcher) {
        val edits = RecordingGoalEdits().apply { currencyResult = Result.failure(IllegalStateException("offline")) }
        val vm = model(edits)
        advanceUntilIdle(); vm.updateName("餐饮"); vm.updateTargetAmount("1200"); vm.submit()
        assertTrue(edits.createCalls.isEmpty())
        assertFalse(vm.state.value.canSubmit)
        edits.currencyResult = Result.success(CurrencyCode.JPY)
        vm.retryCurrency(); advanceUntilIdle()
        vm.updateTargetAmount("12.50"); vm.submit(); advanceUntilIdle()
        assertNotNull(vm.state.value.formError)
        assertTrue(edits.createCalls.isEmpty())
        vm.updateTargetAmount("1200")
        assertTrue(vm.state.value.canSubmit)
    }

    @Test fun oldCreateCompletionCannotNavigateTheReplacementBinding() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val edits = RecordingGoalEdits().apply { createGate = { withContext(NonCancellable) { gate.await() } } }
        val vm = model(edits)
        advanceUntilIdle(); vm.updateName("旧目标"); vm.updateTargetAmount("100"); vm.submit(); advanceUntilIdle()
        edits.access.value = edits.access.value!!.let { it.copy(binding = it.binding.copy(sessionGeneration = "session-2")) }
        advanceUntilIdle(); vm.updateName("新草稿")
        gate.complete(Unit); advanceUntilIdle()
        assertNull(vm.state.value.createdPublicId)
        assertEquals("新草稿", vm.state.value.name)
        assertFalse(vm.state.value.isSubmitting)
    }

    @Test fun missingSelectedCreationCannotSwitchToAnotherPendingOriginal() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        edits.create(edits.currentAccess()!!.binding, com.ticketbox.domain.model.GoalDraft("Other", "2026-09", 1200, homeCurrencyCode = "JPY"), "other-original")
        val vm = model(edits)
        vm.reset("2026-08", originalId = 999)
        advanceUntilIdle()
        assertNull(vm.state.value.pending)
        assertEquals(999L, vm.state.value.originalSubmissionId)
        assertNotNull(vm.state.value.formError)
        assertFalse(vm.state.value.canSubmit)
        vm.updateName("Replacement"); vm.updateTargetAmount("1500"); vm.submit()
        advanceUntilIdle()
        assertEquals(1, edits.createCalls.size)
    }

    @Test fun reentryFromTheListPreservesTheChosenMonthAndEntireUnsubmittedDraft() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        val vm = model(edits)
        vm.reset("2026-09")
        advanceUntilIdle()
        vm.updateName("  十月旅行  ")
        vm.updateTargetAmount("00120.00")
        vm.updateCategory("出行")
        vm.shiftMonth(1)
        val original = vm.state.value
        // The list still displays September when its Create entry is opened again.
        vm.reset("2026-09")
        advanceUntilIdle()
        assertEquals(original.name, vm.state.value.name)
        assertEquals("00120.00", vm.state.value.targetAmountInput)
        assertEquals("2026-10", vm.state.value.month)
        assertEquals("出行", vm.state.value.category)
        assertEquals(original.ledgerCurrency, vm.state.value.ledgerCurrency)
        assertNull(vm.state.value.pending)
        assertNull(vm.state.value.createdPublicId)
        assertTrue(edits.createCalls.isEmpty())
        assertTrue(edits.creations.value.isEmpty())
    }

    @Test fun newDraftAndExplicitOriginalRecoveryDoNotConsumeEachOther() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        edits.create(requireNotNull(edits.currentAccess()).binding,
            com.ticketbox.domain.model.GoalDraft("九月原目标", "2026-09", 1200, homeCurrencyCode = "JPY"), "separate-original")
        val original = edits.creations.value.single()
        val vm = model(edits)
        vm.reset("2026-10")
        advanceUntilIdle()
        assertNull(vm.state.value.pending)
        assertEquals("", vm.state.value.name)
        assertEquals("2026-10", vm.state.value.month)
        vm.updateName("  十月独立目标  ")
        vm.updateTargetAmount("0009.00")
        val draft = vm.state.value
        val failed = original.copy(row = original.row.copy(
            status = com.ticketbox.data.local.PendingMutationStatus.Failed, lastError = "client_upgrade_required"))
        edits.creations.value = listOf(failed)
        advanceUntilIdle()
        assertEquals(draft, vm.state.value)
        vm.reset("2026-09", originalId = original.row.id)
        advanceUntilIdle()
        assertEquals(failed, vm.state.value.pending)
        assertEquals("九月原目标", vm.state.value.name)
        assertEquals("JPY", vm.state.value.ledgerCurrency?.storageKey)
        assertTrue(requireNotNull(vm.state.value.pending).canRetry)
        vm.reset("2026-10")
        advanceUntilIdle()
        assertEquals(draft, vm.state.value)
        assertEquals(original.request, edits.creations.value.single().request)
        assertEquals(original.row.idempotencyKey, edits.creations.value.single().row.idempotencyKey)
        assertEquals(1, edits.createCalls.size)
        assertNull(vm.state.value.createdPublicId)
    }
}
