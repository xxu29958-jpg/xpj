package com.ticketbox.viewmodel

import com.ticketbox.data.repository.create

import androidx.lifecycle.SavedStateHandle
import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.CurrencyCode
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.NonCancellable
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlinx.coroutines.withContext
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class CreateSpendingGoalSavedStateTest {
    private val dispatcher = StandardTestDispatcher()
    private val models = mutableListOf<CreateSpendingGoalViewModel>()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun close() { models.forEach { it.viewModelScope.cancel() }; Dispatchers.resetMain() }
    private fun model(edits: RecordingGoalEdits, saved: SavedStateHandle = SavedStateHandle()) =
        CreateSpendingGoalViewModel(edits, savedStateHandle = saved).also { models += it }
    private fun snapshot(saved: SavedStateHandle) = SavedStateHandle(saved.keys().associateWith { saved.get<Any?>(it) })

    @Test fun constructingTheListOwnerDoesNotExposeAnEmptyContinueTaskButOpeningTheFormDoes() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        val vm = model(edits)
        advanceUntilIdle()
        assertFalse(vm.state.value.hasDraft)
        assertFalse(vm.state.value.isViewingOriginal)
        vm.reset("2026-09"); advanceUntilIdle()
        assertTrue(vm.state.value.hasDraft)
        assertEquals("", vm.state.value.name)
        val key = vm.state.value.creationKey
        vm.reset("2026-10"); advanceUntilIdle()
        assertEquals("2026-09", vm.state.value.month)
        assertEquals(key, vm.state.value.creationKey)
        assertTrue(edits.createCalls.isEmpty())
    }

    @Test fun savedStateKeepsRawJpyMonthCategoryAndReadonlyReviewInTheCompleteOriginalBinding() = runTest(dispatcher) {
        val edits = RecordingGoalEdits().apply { currencyResult = Result.success(CurrencyCode.JPY) }
        val saved = SavedStateHandle()
        val vm = model(edits, saved)
        vm.reset("2026-09"); advanceUntilIdle()
        vm.updateName("  十月旅行  "); vm.updateTargetAmount("001200"); vm.updateCategory("  出行  "); vm.shiftMonth(1)
        val draft = vm.state.value
        vm.viewModelScope.cancel()
        edits.currencyResult = Result.success(CurrencyCode.CNY)
        edits.access.value = requireNotNull(edits.access.value).copy(canModify = false)
        val reopened = model(edits, snapshot(saved))
        reopened.reset("2026-09"); advanceUntilIdle()
        assertEquals(draft.name, reopened.state.value.name)
        assertEquals("001200", reopened.state.value.targetAmountInput)
        assertEquals("  出行  ", reopened.state.value.category)
        assertEquals("2026-10", reopened.state.value.month)
        assertEquals(CurrencyCode.JPY, reopened.state.value.ledgerCurrency)
        assertEquals(draft.creationKey, reopened.state.value.creationKey)
        assertTrue(reopened.state.value.hasDraft)
        assertFalse(reopened.state.value.canSubmit)
        reopened.retryOriginal(); reopened.submit(); advanceUntilIdle()
        assertTrue(edits.createCalls.isEmpty())
        reopened.discardDraft(); advanceUntilIdle()
        assertFalse(reopened.state.value.hasDraft)
        assertNotEquals(draft.creationKey, reopened.state.value.creationKey)
    }

    @Test fun everyFullBindingChangeHidesTheOldDraftAndReturningToItsBindingRestoresIt() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        val origin = requireNotNull(edits.access.value)
        val vm = model(edits)
        advanceUntilIdle(); vm.updateName("原账本草稿"); vm.updateTargetAmount("001.00")
        val key = vm.state.value.creationKey
        val replacements = listOf(origin.binding.copy(serverUrl = "https://other.example"),
            origin.binding.copy(ownerKey = "other-owner"), origin.binding.copy(ledgerId = "other-ledger"),
            origin.binding.copy(sessionGeneration = "other-session"), origin.binding.copy(bindingRevision = "other-revision"))
        for (replacement in replacements) {
            edits.access.value = origin.copy(binding = replacement)
            advanceUntilIdle()
            assertEquals("", vm.state.value.name)
            assertFalse(vm.state.value.hasDraft)
            assertNotEquals(key, vm.state.value.creationKey)
            edits.access.value = origin
            advanceUntilIdle()
            assertEquals("原账本草稿", vm.state.value.name)
            assertEquals("001.00", vm.state.value.targetAmountInput)
            assertEquals(key, vm.state.value.creationKey)
        }
        assertTrue(edits.createCalls.isEmpty())
    }

    @Test fun preSaveSnapshotRejoinsTheSameKeyAndCannotReplayAnOlderBody() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        val saved = SavedStateHandle()
        val vm = model(edits, saved)
        vm.reset("2026-09"); advanceUntilIdle()
        vm.updateName("旧输入"); vm.updateTargetAmount("001.00")
        val preSave = snapshot(saved)
        val key = vm.state.value.creationKey
        vm.updateName("较新创建意图"); vm.updateTargetAmount("240.00"); vm.submit(); advanceUntilIdle()
        val accepted = edits.creations.value.single()
        vm.viewModelScope.cancel()
        val reopened = model(edits, preSave)
        reopened.reset("2026-09"); advanceUntilIdle()
        assertEquals("较新创建意图", reopened.state.value.name)
        assertEquals(accepted, reopened.state.value.pending)
        assertEquals(key, reopened.state.value.creationKey)
        reopened.submit(); advanceUntilIdle()
        assertEquals(1, edits.createCalls.size)
        assertEquals(listOf(key), edits.createKeys)
        assertNull(reopened.state.value.createdPublicId)
        edits.creations.value = listOf(accepted.copy(row = accepted.row.copy(status = PendingMutationStatus.Done),
            confirmed = spendingGoal().copy(name = "较新创建意图", targetAmountCents = 24000, month = "2026-09")))
        advanceUntilIdle()
        assertEquals("goal-1", reopened.state.value.createdPublicId)
    }

    @Test fun losingTheCallbackAfterLocalAcceptanceRestoresOneOriginalFromItsPreSaveSnapshot() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        val gate = CompletableDeferred<Unit>()
        edits.afterCreateAccepted = { gate.await() }
        val saved = SavedStateHandle()
        val vm = model(edits, saved)
        advanceUntilIdle(); vm.updateName("本地已收但回调未到"); vm.updateTargetAmount("12.00")
        val preSave = snapshot(saved)
        val key = vm.state.value.creationKey
        vm.submit(); advanceUntilIdle()
        assertEquals(1, edits.creations.value.size)
        vm.viewModelScope.cancel()
        val reopened = model(edits, preSave); advanceUntilIdle()
        assertEquals(edits.creations.value.single(), reopened.state.value.pending)
        assertEquals(key, reopened.state.value.creationKey)
        reopened.submit(); advanceUntilIdle()
        assertEquals(1, edits.createCalls.size)
        assertEquals(1, edits.creations.value.size)
        assertNull(reopened.state.value.createdPublicId)
    }

    @Test fun createFailureAndOriginalLookupFailureRestoreWithTheSameTaskAndCanBeRechecked() = runTest(dispatcher) {
        val edits = RecordingGoalEdits().apply { createFailure = RepositoryException("原创建失败", "invalid_request") }
        val saved = SavedStateHandle()
        val vm = model(edits, saved)
        advanceUntilIdle(); vm.updateName("失败稿"); vm.updateTargetAmount("19.00"); vm.submit(); advanceUntilIdle()
        val failed = vm.state.value
        assertNotNull(failed.formError)
        assertTrue(failed.editable)
        assertFalse(failed.acceptanceUncertain)
        vm.viewModelScope.cancel()
        val reopened = model(edits, snapshot(saved)); advanceUntilIdle()
        assertEquals(failed.name, reopened.state.value.name)
        assertEquals(failed.creationKey, reopened.state.value.creationKey)
        assertEquals(failed.formError, reopened.state.value.formError)
        edits.originalLookupFailure = RepositoryException("原提交暂时不可核对")
        reopened.retryOriginal(); advanceUntilIdle()
        assertTrue(reopened.state.value.acceptanceUncertain)
        assertFalse(reopened.state.value.canSubmit)
        edits.originalLookupFailure = null
        edits.createFailure = null
        reopened.retryOriginal(); advanceUntilIdle()
        assertFalse(reopened.state.value.acceptanceUncertain)
        reopened.submit(); advanceUntilIdle()
        assertEquals(1, edits.creations.value.size)
        assertEquals(listOf(failed.creationKey, failed.creationKey), edits.createKeys)
    }

    @Test fun explicitOtherOriginalSurvivesRecreationWithoutEatingTheIndependentSavedDraft() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        edits.create(requireNotNull(edits.currentAccess()).binding,
            com.ticketbox.domain.model.GoalDraft("旧原提交", "2026-09", 1200, homeCurrencyCode = "JPY"), "other-key")
        val original = edits.creations.value.single()
        val saved = SavedStateHandle()
        val vm = model(edits, saved)
        vm.reset("2026-10"); advanceUntilIdle()
        vm.updateName("  独立新稿  "); vm.updateTargetAmount("0009.00"); vm.updateCategory("新类别")
        val draft = vm.state.value
        vm.reset("2026-09", original.row.id); advanceUntilIdle()
        assertTrue(vm.state.value.hasDraft)
        assertTrue(vm.state.value.isViewingOriginal)
        assertFalse(vm.state.value.canDiscardDraft)
        vm.viewModelScope.cancel()
        val reopened = model(edits, snapshot(saved)); advanceUntilIdle()
        assertEquals(original, reopened.state.value.pending)
        reopened.discardDraft()
        assertEquals(original, reopened.state.value.pending)
        reopened.reset("2026-09"); advanceUntilIdle()
        assertEquals(draft, reopened.state.value)
        assertEquals(original, edits.creations.value.single())
    }

    @Test fun missingOriginalAfterAnActualPublicationAttemptNeverUnlocksTheRawDraftForReplay() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        val saved = SavedStateHandle()
        val gate = CompletableDeferred<Unit>()
        var beforeCallback: SavedStateHandle? = null
        edits.afterCreateAccepted = { beforeCallback = snapshot(saved); gate.await() }
        val vm = model(edits, saved)
        advanceUntilIdle(); vm.updateName("  已发布但结果未知  "); vm.updateTargetAmount("120.000")
        val key = vm.state.value.creationKey
        vm.submit(); advanceUntilIdle()
        assertEquals(1, edits.createCalls.size)
        assertNotNull(beforeCallback)
        edits.creations.value = emptyList()
        vm.viewModelScope.cancel()
        val reopened = model(edits, requireNotNull(beforeCallback)); advanceUntilIdle()
        assertEquals("  已发布但结果未知  ", reopened.state.value.name)
        assertEquals("120.000", reopened.state.value.targetAmountInput)
        assertEquals(key, reopened.state.value.creationKey)
        assertTrue(reopened.state.value.acceptanceUncertain)
        assertFalse(reopened.state.value.canSubmit)
        reopened.retryOriginal(); advanceUntilIdle(); reopened.submit(); advanceUntilIdle()
        assertEquals(1, edits.createCalls.size)
        assertTrue(reopened.state.value.acceptanceUncertain)
        assertEquals("120.000", reopened.state.value.targetAmountInput)
        assertTrue(reopened.state.value.canDiscardDraft)
        reopened.discardDraft(); advanceUntilIdle()
        assertFalse(reopened.state.value.acceptanceUncertain)
        assertNotEquals(key, reopened.state.value.creationKey)
    }

    @Test fun lookupFailureBeforePublicationCanBeRecheckedWithoutMarkingTheTaskAsAlreadyPublished() = runTest(dispatcher) {
        val edits = RecordingGoalEdits().apply { originalLookupFailure = RepositoryException("暂时无法核对") }
        val vm = model(edits)
        advanceUntilIdle()
        assertTrue(vm.state.value.acceptanceUncertain)
        assertTrue(edits.createCalls.isEmpty())
        edits.originalLookupFailure = null
        vm.retryOriginal(); advanceUntilIdle()
        assertFalse(vm.state.value.acceptanceUncertain)
        vm.updateName("未发布的新稿"); vm.updateTargetAmount("12.00"); vm.submit(); advanceUntilIdle()
        assertEquals(1, edits.createCalls.size)
        assertEquals(1, edits.creations.value.size)
    }

    @Test fun confirmedOtherOriginalCanNavigateWithoutConsumingTheReadonlyIndependentDraft() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        edits.create(requireNotNull(edits.currentAccess()).binding,
            com.ticketbox.domain.model.GoalDraft("旧原提交", "2026-09", 1200, homeCurrencyCode = "JPY"), "confirmed-other-key")
        val accepted = edits.creations.value.single()
        val vm = model(edits)
        vm.reset("2026-10"); advanceUntilIdle()
        vm.updateName("  必须保留的独立稿  "); vm.updateTargetAmount("0009.00"); vm.updateCategory("出行")
        val draft = vm.state.value
        edits.access.value = requireNotNull(edits.access.value).copy(canModify = false)
        edits.creations.value = listOf(accepted.copy(row = accepted.row.copy(status = PendingMutationStatus.Done),
            confirmed = spendingGoal().copy(homeCurrencyCode = "JPY", targetAmountCents = 1200)))
        vm.reset("2026-09", accepted.row.id); advanceUntilIdle()
        assertEquals("goal-1", vm.state.value.createdPublicId)
        assertTrue(vm.state.value.hasDraft)
        assertTrue(vm.state.value.isViewingOriginal)
        vm.consumeCreated(); advanceUntilIdle()
        assertEquals(draft.name, vm.state.value.name)
        assertEquals(draft.targetAmountInput, vm.state.value.targetAmountInput)
        assertEquals(draft.month, vm.state.value.month)
        assertEquals(draft.category, vm.state.value.category)
        assertEquals(draft.creationKey, vm.state.value.creationKey)
        assertTrue(vm.state.value.hasDraft)
        assertFalse(vm.state.value.isViewingOriginal)
        assertFalse(vm.state.value.canSubmit)
        assertNull(vm.state.value.createdPublicId)
        assertEquals(1, edits.createCalls.size)
        assertEquals(1, edits.creations.value.size)
    }

    @Test fun unknownAndAbandonedOriginalKeepRawInputButCanReleaseOnlyTheLocalDraft() = runTest(dispatcher) {
        for (status in listOf(PendingMutationStatus.Unknown, PendingMutationStatus.Abandoned)) {
            val edits = RecordingGoalEdits()
            val saved = SavedStateHandle()
            val vm = model(edits, saved)
            advanceUntilIdle(); vm.updateName("  原始输入  "); vm.updateTargetAmount("10.000"); vm.submit(); advanceUntilIdle()
            val raw = edits.creations.value.single().let { it.copy(row = it.row.copy(status = status)) }
            edits.creations.value = listOf(raw)
            vm.viewModelScope.cancel()
            val reopened = model(edits, snapshot(saved)); advanceUntilIdle()
            assertEquals("  原始输入  ", reopened.state.value.name)
            assertEquals("10.000", reopened.state.value.targetAmountInput)
            assertEquals(raw, reopened.state.value.pending)
            assertFalse(reopened.state.value.canSubmit)
            reopened.retryOriginal(); advanceUntilIdle()
            assertEquals(raw, reopened.state.value.pending)
            val key = reopened.state.value.creationKey
            reopened.discardDraft(); advanceUntilIdle()
            assertNotEquals(key, reopened.state.value.creationKey)
            assertTrue(reopened.state.value.editable)
            assertFalse(reopened.state.value.hasDraft)
            assertEquals(raw, edits.creations.value.single())
        }
    }

    @Test fun busyTaskCannotDiscardAndItsLateResultCannotConsumeReplacementBindingDraft() = runTest(dispatcher) {
        val edits = RecordingGoalEdits()
        val gate = CompletableDeferred<Unit>()
        edits.createGate = { withContext(NonCancellable) { gate.await() } }
        val vm = model(edits)
        advanceUntilIdle(); vm.updateName("旧任务"); vm.updateTargetAmount("100"); vm.submit(); advanceUntilIdle()
        val key = vm.state.value.creationKey
        vm.discardDraft()
        assertEquals(key, vm.state.value.creationKey)
        assertEquals("旧任务", vm.state.value.name)
        edits.access.value = requireNotNull(edits.access.value).let { it.copy(binding = it.binding.copy(bindingRevision = "next-binding")) }
        advanceUntilIdle(); vm.updateName("替代绑定的独立草稿")
        val replacementKey = vm.state.value.creationKey
        gate.complete(Unit); advanceUntilIdle()
        assertEquals("替代绑定的独立草稿", vm.state.value.name)
        assertEquals(replacementKey, vm.state.value.creationKey)
        assertNull(vm.state.value.pending)
        assertNull(vm.state.value.createdPublicId)
    }
}
