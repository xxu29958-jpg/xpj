package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.dto.GoalCreateRequestDto
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.PendingGoalCreation
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
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

class DebtGoalCreationSavedStateTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setUp() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test fun restoredRawDraftAndLookupFailureCannotPublishAnotherTask() = runTest(dispatcher) {
        val handle = SavedStateHandle()
        val edits = FakeCreateGoalEdits()
        val debts = FakeCreateDebtActions(listResult = Result.success(listOf(sampleDebt("a"))))
        val first = CreateDebtGoalViewModel(edits, debts, FakeDebtWriteActions(), handle)
        first.reload(); advanceUntilIdle()
        first.updateName("  原还债安排  "); first.toggleDebt("a")
        val key = first.state.value.creationKey
        first.viewModelScope.cancel()
        edits.lookupFailure = IOException("原提交暂时读不到")
        val restored = CreateDebtGoalViewModel(edits, debts, FakeDebtWriteActions(), copyHandle(handle))
        restored.reload(); advanceUntilIdle()
        assertEquals("  原还债安排  ", restored.state.value.name)
        assertEquals(setOf("a"), restored.state.value.selectedDebtIds)
        assertEquals(key, restored.state.value.creationKey)
        assertTrue(restored.state.value.acceptanceUncertain)
        assertNotNull(restored.state.value.formError)
        restored.submit(); advanceUntilIdle()
        assertTrue(edits.keys.isEmpty())
        restored.viewModelScope.cancel()
    }

    @Test fun lostLocalAcknowledgementFindsOriginalRoomIntentWithoutRebuildingItsDebtSelection() = runTest(dispatcher) {
        val handle = SavedStateHandle()
        val edits = FakeCreateGoalEdits(createResult = Result.failure(IOException("ack lost"))).apply { persistBeforeFailure = true }
        val debts = FakeCreateDebtActions(listResult = Result.success(listOf(sampleDebt("a"), sampleDebt("b"))))
        val first = CreateDebtGoalViewModel(edits, debts, FakeDebtWriteActions(), handle)
        first.reload(); advanceUntilIdle()
        first.updateName("  原任务  "); first.toggleDebt("b"); first.toggleDebt("a")
        first.submit(); advanceUntilIdle()
        val original = edits.rows.value.single()
        assertEquals(listOf("a", "b"), original.request?.debtPublicIds)
        assertNull(first.state.value.createdPublicId)
        first.viewModelScope.cancel()
        debts.listResult = Result.success(emptyList())
        val restored = CreateDebtGoalViewModel(edits, debts, FakeDebtWriteActions(), copyHandle(handle))
        restored.reload(); advanceUntilIdle()
        assertEquals(original.row, restored.state.value.pending?.row)
        assertEquals("  原任务  ", restored.state.value.name)
        assertEquals(setOf("a", "b"), restored.state.value.selectedDebtIds)
        restored.submit(); advanceUntilIdle()
        assertEquals(1, edits.keys.size)
        edits.rows.value = listOf(original.copy(row = original.row.copy(status = PendingMutationStatus.Done),
            confirmed = debtCreationGoal("confirmed")))
        advanceUntilIdle()
        assertEquals("confirmed", restored.state.value.createdPublicId)
        restored.viewModelScope.cancel()
    }

    @Test fun olderSnapshotShowsTheAcceptedNameAndSelectionInsteadOfItsOutdatedInputs() = runTest(dispatcher) {
        val handle = SavedStateHandle()
        val edits = FakeCreateGoalEdits(createResult = Result.failure(IOException("ack lost"))).apply { persistBeforeFailure = true }
        val debts = FakeCreateDebtActions(listResult = Result.success(listOf(sampleDebt("a"), sampleDebt("b"))))
        val first = CreateDebtGoalViewModel(edits, debts, FakeDebtWriteActions(), handle)
        first.reload(); advanceUntilIdle()
        first.updateName("  较早原稿  "); first.toggleDebt("a")
        val earlier = copyHandle(handle)
        val key = first.state.value.creationKey
        first.updateName("  实际接受的任务  "); first.toggleDebt("a"); first.toggleDebt("b")
        first.submit(); advanceUntilIdle()
        val original = edits.rows.value.single()
        first.viewModelScope.cancel()
        debts.listResult = Result.success(emptyList())
        val restored = CreateDebtGoalViewModel(edits, debts, FakeDebtWriteActions(), earlier)
        restored.reload(); advanceUntilIdle()
        assertEquals(original.row, restored.state.value.pending?.row)
        assertEquals(key, restored.state.value.creationKey)
        assertEquals("实际接受的任务", restored.state.value.name)
        assertEquals(setOf("b"), restored.state.value.selectedDebtIds)
        assertFalse(restored.state.value.editable)
        assertNull(restored.state.value.createdPublicId)
        restored.submit(); advanceUntilIdle()
        assertEquals(1, edits.keys.size)
        assertEquals(original, edits.rows.value.single())
        restored.viewModelScope.cancel()
    }

    @Test fun completeBindingAndReadonlyKeepOriginalDraftWithoutShowingItInAnotherSession() = runTest(dispatcher) {
        val edits = FakeCreateGoalEdits()
        val writes = FakeDebtWriteActions()
        val vm = CreateDebtGoalViewModel(edits, FakeCreateDebtActions(listResult = Result.success(listOf(sampleDebt("a")))), writes)
        vm.reload(); advanceUntilIdle()
        vm.updateName("保留原稿"); vm.toggleDebt("a")
        val key = vm.state.value.creationKey
        val other = adjustmentBinding().copy(sessionGeneration = "other-session", bindingRevision = "other-binding")
        edits.access.value = LedgerAccessContext(other, true); writes.access.value = LedgerAccessContext(other, true)
        advanceUntilIdle()
        assertEquals("", vm.state.value.name)
        assertTrue(vm.state.value.selectedDebtIds.isEmpty())
        edits.access.value = LedgerAccessContext(adjustmentBinding(), false)
        writes.access.value = LedgerAccessContext(adjustmentBinding(), false)
        advanceUntilIdle()
        assertEquals("保留原稿", vm.state.value.name)
        assertEquals(setOf("a"), vm.state.value.selectedDebtIds)
        assertEquals(key, vm.state.value.creationKey)
        assertFalse(vm.state.value.editable)
        vm.updateName("不应覆盖"); vm.submit(); advanceUntilIdle()
        assertEquals("保留原稿", vm.state.value.name)
        assertTrue(edits.keys.isEmpty())
        vm.viewModelScope.cancel()
    }

    @Test fun unknownAndAbandonedOriginalsKeepRawInputAndNeverBecomeNewCreates() = runTest(dispatcher) {
        val handle = SavedStateHandle()
        val edits = FakeCreateGoalEdits(createResult = Result.failure(IOException("ack lost"))).apply { persistBeforeFailure = true }
        val debts = FakeCreateDebtActions(listResult = Result.success(listOf(sampleDebt("a"))))
        val vm = CreateDebtGoalViewModel(edits, debts, FakeDebtWriteActions(), handle)
        vm.reload(); advanceUntilIdle()
        vm.updateName("  原始输入  "); vm.toggleDebt("a"); vm.submit(); advanceUntilIdle()
        val original = edits.rows.value.single()
        for (status in listOf(PendingMutationStatus.Unknown, PendingMutationStatus.Abandoned)) {
            edits.rows.value = listOf(original.copy(row = original.row.copy(status = status)))
            vm.reload(); advanceUntilIdle()
            assertEquals(status, vm.state.value.pending?.row?.status)
            assertEquals("  原始输入  ", vm.state.value.name)
            assertEquals(setOf("a"), vm.state.value.selectedDebtIds)
            assertFalse(vm.state.value.canSubmit)
            assertNull(vm.state.value.createdPublicId)
            vm.submit(); advanceUntilIdle()
            assertEquals(1, edits.keys.size)
        }
        vm.viewModelScope.cancel()
    }

    @Test fun explicitOriginalAndItsLateReceiptCannotConsumeTheSeparateRawDraft() = runTest(dispatcher) {
        val edits = FakeCreateGoalEdits()
        val vm = CreateDebtGoalViewModel(edits, FakeCreateDebtActions(listResult = Result.success(listOf(sampleDebt("a")))), FakeDebtWriteActions())
        vm.reload(); advanceUntilIdle()
        vm.updateName("  独立草稿  "); vm.toggleDebt("a")
        val ownKey = vm.state.value.creationKey
        val other = PendingGoalCreation(debtCreationRow(adjustmentBinding(), "other-key", 7),
            GoalCreateRequestDto(name = "另一个原提交", goalType = "debt_repayment", debtPublicIds = listOf("cleared")), null)
        edits.origins[7] = adjustmentBinding(); edits.rows.value = listOf(other)
        vm.openOriginal(7); advanceUntilIdle()
        assertEquals("另一个原提交", vm.state.value.name)
        assertEquals(setOf("cleared"), vm.state.value.selectedDebtIds)
        vm.reload(); advanceUntilIdle()
        edits.rows.value = listOf(other.copy(row = other.row.copy(status = PendingMutationStatus.Done),
            confirmed = debtCreationGoal("other-confirmed")))
        advanceUntilIdle()
        assertNull(vm.state.value.createdPublicId)
        assertEquals("  独立草稿  ", vm.state.value.name)
        vm.openOriginal(7); advanceUntilIdle()
        assertEquals("other-confirmed", vm.state.value.createdPublicId)
        vm.consumeCreated(); advanceUntilIdle()
        assertEquals("  独立草稿  ", vm.state.value.name)
        assertEquals(setOf("a"), vm.state.value.selectedDebtIds)
        assertEquals(ownKey, vm.state.value.creationKey)
        assertTrue(edits.keys.isEmpty())
        vm.viewModelScope.cancel()
    }

    @Test fun failedOriginalRetryAndExplicitStopKeepTheSameRowAndRawDraft() = runTest(dispatcher) {
        val edits = FakeCreateGoalEdits(createResult = Result.failure(IOException("ack lost"))).apply { persistBeforeFailure = true }
        val vm = CreateDebtGoalViewModel(edits, FakeCreateDebtActions(listResult = Result.success(listOf(sampleDebt("a")))), FakeDebtWriteActions())
        vm.reload(); advanceUntilIdle()
        vm.updateName("  待核对原稿  "); vm.toggleDebt("a"); vm.submit(); advanceUntilIdle()
        val original = edits.rows.value.single()
        val failed = original.copy(row = original.row.copy(status = PendingMutationStatus.Failed, lastError = "runtime_version_mismatch"))
        edits.rows.value = listOf(failed); advanceUntilIdle()
        assertTrue(requireNotNull(vm.state.value.pending).canRetry)
        vm.recover(requireNotNull(vm.state.value.pending), drop = false); advanceUntilIdle()
        assertEquals(original.row.id, vm.state.value.pending?.row?.id)
        assertEquals(PendingMutationStatus.Pending, vm.state.value.pending?.row?.status)
        edits.rows.value = listOf(failed); advanceUntilIdle()
        edits.access.value = LedgerAccessContext(adjustmentBinding(), false); advanceUntilIdle()
        assertFalse(vm.state.value.canModify)
        vm.recover(requireNotNull(vm.state.value.pending), drop = false); advanceUntilIdle()
        assertEquals(PendingMutationStatus.Failed, vm.state.value.pending?.row?.status)
        vm.recover(requireNotNull(vm.state.value.pending), drop = true); advanceUntilIdle()
        assertEquals(original.row.id, vm.state.value.pending?.row?.id)
        assertEquals(PendingMutationStatus.Abandoned, vm.state.value.pending?.row?.status)
        assertEquals("  待核对原稿  ", vm.state.value.name)
        assertEquals(setOf("a"), vm.state.value.selectedDebtIds)
        assertFalse(vm.state.value.canSubmit)
        assertEquals(1, edits.keys.size)
        vm.discardDraft(); advanceUntilIdle()
        assertEquals("", vm.state.value.name)
        assertEquals(PendingMutationStatus.Abandoned, edits.rows.value.single().row.status)
        vm.viewModelScope.cancel()
    }

    @Test fun knownLocalRejectionKeepsErrorOnReentryAndAllowsCorrectionWithTheOriginalKey() = runTest(dispatcher) {
        val edits = FakeCreateGoalEdits(createResult = Result.success(debtCreationGoal("completed")))
        val vm = CreateDebtGoalViewModel(edits, FakeCreateDebtActions(listResult = Result.success(listOf(sampleDebt("a")))), FakeDebtWriteActions())
        vm.reload(); advanceUntilIdle()
        val rawName = "债".repeat(81)
        vm.updateName(rawName); vm.toggleDebt("a")
        val key = vm.state.value.creationKey
        vm.submit(); advanceUntilIdle()
        assertNotNull(vm.state.value.formError)
        assertTrue(edits.keys.isEmpty(), "The original owner refuses invalid input before accepting a Room command")
        vm.reload(); advanceUntilIdle()
        assertEquals(rawName, vm.state.value.name)
        assertEquals(setOf("a"), vm.state.value.selectedDebtIds)
        assertEquals(key, vm.state.value.creationKey)
        assertNotNull(vm.state.value.formError)
        assertTrue(vm.state.value.editable)
        vm.updateName("修正后的原任务"); vm.submit(); advanceUntilIdle()
        assertEquals(listOf(key), edits.keys)
        assertEquals("completed", vm.state.value.createdPublicId)
        vm.viewModelScope.cancel()
    }

    private fun copyHandle(handle: SavedStateHandle) = SavedStateHandle(handle.keys().associateWith { handle.get<Any?>(it) })
}
