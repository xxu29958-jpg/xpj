package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingGoalEdit
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.GoalUpdate
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
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class SpendingGoalDetailViewModelTest {
    private val dispatcher = StandardTestDispatcher()
    private val models = mutableListOf<SpendingGoalDetailViewModel>()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun close() { models.forEach { it.viewModelScope.cancel() }; Dispatchers.resetMain() }
    private fun model(reports: RecordingSpendingGoalActions, edits: RecordingGoalEdits) =
        SpendingGoalDetailViewModel(reports, edits).also { models += it; it.load("goal-1") }

    @Test fun savePublishesOnceAndKeepsCanonicalProgress() = runTest(dispatcher) {
        val reports = RecordingSpendingGoalActions()
        val gate = CompletableDeferred<Unit>()
        val edits = RecordingGoalEdits().apply { saveGate = { gate.await() } }
        val vm = model(reports, edits)
        advanceUntilIdle()
        vm.beginEdit()
        vm.updateField(SpendingGoalEditField.Amount, "350.00")
        vm.updateField(SpendingGoalEditField.Category, "")
        vm.save(); vm.save()
        advanceUntilIdle()
        assertEquals(listOf(GoalUpdate(1, "本月外卖", "2026-07", 35000, "", "CNY")), edits.saves)
        assertEquals(20000, vm.state.value.goal?.targetAmountCents)
        gate.complete(Unit)
        advanceUntilIdle()
        assertFalse(vm.state.value.isEditing)
        assertEquals(12000, vm.state.value.goal?.remainingAmountCents)
        assertEquals(0, vm.state.value.mutationRevision)
    }

    @Test fun jpyInputAndReentryKeepTheOriginalDraft() = runTest(dispatcher) {
        val edits = RecordingGoalEdits().apply { currencyResult = Result.success(CurrencyCode.CNY) }
        val reports = RecordingSpendingGoalActions().apply {
            goalResult = Result.success(spendingGoal().copy(homeCurrencyCode = "JPY"))
        }
        val vm = model(reports, edits)
        advanceUntilIdle()
        vm.beginEdit()
        assertEquals("20000", vm.state.value.targetAmountInput)
        vm.updateField(SpendingGoalEditField.Amount, "1200")
        vm.load("goal-1")
        assertEquals("1200", vm.state.value.targetAmountInput)
        vm.save()
        advanceUntilIdle()
        assertEquals(1200, edits.saves.single().targetAmountCents)
        assertEquals("JPY", edits.saves.single().homeCurrencyCode)
    }

    @Test fun unknownCurrencyIsRecoverableAndNeverEnablesWriting() = runTest(dispatcher) {
        val edits = RecordingGoalEdits().apply { currencyResult = Result.failure(IllegalStateException("offline")) }
        val reports = RecordingSpendingGoalActions().apply {
            goalResult = Result.success(spendingGoal().copy(homeCurrencyCode = null))
        }
        val vm = model(reports, edits)
        advanceUntilIdle()
        vm.beginEdit(); vm.save()
        assertFalse(vm.state.value.canSave)
        assertTrue(edits.saves.isEmpty())
        assertNotNull(vm.state.value.formError)
        reports.goalResult = Result.success(spendingGoal().copy(homeCurrencyCode = "JPY"))
        vm.load(); advanceUntilIdle(); vm.beginEdit()
        assertTrue(vm.state.value.isEditing)
    }

    @Test fun pendingAndConfirmedReceiptsRemainDistinctAcrossFailedReads() = runTest(dispatcher) {
        val reports = RecordingSpendingGoalActions()
        val edits = RecordingGoalEdits()
        val vm = model(reports, edits)
        advanceUntilIdle()
        val row = goalRow(PendingMutationStatus.Pending)
        edits.rows.value = listOf(PendingGoalEdit(row, null, null))
        advanceUntilIdle()
        vm.beginEdit(); vm.showArchiveConfirmation(true)
        assertFalse(vm.state.value.isEditing)
        assertFalse(vm.state.value.showArchiveDialog)
        val canonical = spendingGoal(rowVersion = 2).copy(targetAmountCents = 35000, remainingAmountCents = 27000,
            homeCurrencyCode = "JPY")
        edits.rows.value = listOf(PendingGoalEdit(row.copy(status = PendingMutationStatus.Done), null, canonical))
        reports.goalResult = Result.failure(IllegalStateException("read unavailable"))
        advanceUntilIdle(); vm.load(); advanceUntilIdle()
        assertEquals(35000L, vm.state.value.goal?.targetAmountCents)
        assertEquals(27000L, vm.state.value.goal?.remainingAmountCents)
        assertEquals("JPY", vm.state.value.goal?.homeCurrencyCode)
        assertEquals(canonical, vm.state.value.pendingEdits.single().confirmed)
        assertEquals(null, vm.state.value.fetchedAt)
        vm.beginEdit()
        assertTrue(vm.state.value.isEditing)
        assertEquals("35000", vm.state.value.targetAmountInput)
        assertEquals(2L, vm.state.value.goal?.rowVersion)
        vm.cancelEdit()
        reports.goalResult = Result.failure(com.ticketbox.data.repository.RepositoryException("Forbidden", httpStatusCode = 403))
        vm.load(); advanceUntilIdle()
        assertEquals(null, vm.state.value.goal)
        assertEquals(null, vm.state.value.fetchedAt)
        assertEquals(canonical, vm.state.value.pendingEdits.single().confirmed)
        assertFalse(vm.state.value.hasPendingEdit)
        assertNotNull(vm.state.value.loadError)
    }

    @Test fun replacedBindingCannotAdoptAnOldCurrencyOrGoalResult() = runTest(dispatcher) {
        val gate = CompletableDeferred<Unit>()
        val reports = RecordingSpendingGoalActions().apply { goalGate = { withContext(NonCancellable) { gate.await() } } }
        val edits = RecordingGoalEdits()
        val vm = model(reports, edits)
        advanceUntilIdle()
        reports.goalGate = null
        reports.goalResult = Result.success(spendingGoal().copy(name = "新会话目标"))
        edits.access.value = edits.access.value!!.let { it.copy(binding = it.binding.copy(bindingRevision = "binding-2")) }
        advanceUntilIdle()
        gate.complete(Unit); advanceUntilIdle()
        assertEquals("新会话目标", vm.state.value.goal?.name)
        edits.access.value = edits.access.value!!.copy(canModify = false)
        advanceUntilIdle(); vm.beginEdit(); vm.save()
        assertFalse(vm.state.value.canModify)
        assertTrue(edits.saves.isEmpty())
    }

    @Test fun invalidFormAndArchivedGoalNeverPublish() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        val reports = RecordingSpendingGoalActions()
        val vm = model(reports, edits)
        advanceUntilIdle(); vm.beginEdit(); vm.updateField(SpendingGoalEditField.Amount, "0"); vm.save()
        assertNotNull(vm.state.value.formError)
        vm.cancelEdit()
        reports.goalResult = Result.success(spendingGoal(status = "archived", rowVersion = 2))
        vm.load(); advanceUntilIdle(); vm.beginEdit(); vm.save()
        assertFalse(vm.state.value.isEditing)
        assertTrue(edits.saves.isEmpty())
    }

    private fun goalRow(status: PendingMutationStatus) = OutboxRow(
        1, "https://goal.example", "owner", "test-owner", PendingMutationType.UpdateGoal,
        "goal:goal-1", "{}", 1, status, 0, null, "2026-09-08T00:00:00Z", null, null, "original-key")
}
