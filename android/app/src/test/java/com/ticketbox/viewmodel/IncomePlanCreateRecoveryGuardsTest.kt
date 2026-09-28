package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.PendingIncomePlanSubmission
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
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
import kotlin.test.assertNotEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class IncomePlanCreateRecoveryGuardsTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun originalLookupCannotRetireAnotherKeyOrAnyDifferentOriginComponent() = runTest(dispatcher) {
        val source = SavedStateHandle()
        val original = retainedCreation(source, IncomePlanCreationPhase.Publishing)
        val call = IncomePlanCreateCall(original.binding, requireNotNull(original.draft.toRepositoryDraftOrNull()), original.creationKey)
        val binding = original.binding
        val otherCalls = listOf(
            call.copy(creationKey = "other-key"),
            call.copy(binding = binding.copy(serverUrl = "https://other.example.com")),
            call.copy(binding = binding.copy(ledgerId = "other-ledger")),
            call.copy(binding = binding.copy(ownerKey = "other-owner")),
            call.copy(binding = binding.copy(sessionGeneration = "other-session")),
            call.copy(binding = binding.copy(bindingRevision = "other-revision")),
        )
        for (other in otherCalls) {
            val saved = createStateSnapshot(source)
            val repo = FakeIncomePlanCreateRepository().apply { lookupResponder = { _, _ -> Result.success(createSubmission(other)) } }
            val owner = IncomePlanCreateViewModel(repo, saved)
            advanceUntilIdle()
            val retained = assertNotNull(owner.state.value.session)
            assertEquals(original.creationKey, retained.creationKey)
            assertEquals(original.draft, retained.draft.copy(validationError = null))
            assertEquals(IncomePlanCreationPhase.NeedsRecovery, retained.phase)
            assertNull(owner.state.value.publishedRowId)
            assertTrue(repo.creationCalls.isEmpty())
            repo.lookupResponder = { _, _ -> Result.success(createSubmission(call, 91L)) }
            owner.retryPublicationRecovery()
            advanceUntilIdle()
            assertEquals(91L, owner.state.value.publishedRowId)
            assertNull(owner.state.value.session)
        }
    }

    @Test
    fun suspendedAndFailedLookupDoNotBlockIdentityObserverOrExposeOldRawInput() = runTest(dispatcher) {
        val saved = SavedStateHandle()
        val original = retainedCreation(saved, IncomePlanCreationPhase.Publishing)
        val release = CompletableDeferred<Result<PendingIncomePlanSubmission?>>()
        val repo = FakeIncomePlanCreateRepository().apply { lookupResponder = { _, _ -> release.await() } }
        val owner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        assertTrue(owner.state.value.isRestoring)
        owner.updateDraftLabel("查验中覆盖")
        assertEquals(original, owner.state.value.session)
        val other = original.binding.copy(sessionGeneration = "other-session")
        repo.activeAccessFlow.value = LedgerAccessContext(other, canModify = false)
        advanceUntilIdle()
        assertEquals(other, owner.state.value.binding)
        assertNull(owner.state.value.session)
        release.complete(Result.failure(IllegalStateException("读取失败")))
        advanceUntilIdle()
        assertNull(owner.state.value.session)
        assertNull(owner.state.value.publishedRowId)
        repo.activeAccessFlow.value = LedgerAccessContext(original.binding, canModify = false)
        advanceUntilIdle()
        assertFalse(owner.state.value.isRestoring)
        val retained = assertNotNull(owner.state.value.session)
        assertEquals(original.binding, retained.binding)
        assertEquals(original.creationKey, retained.creationKey)
        assertEquals("  原稿  ", retained.draft.label)
        assertEquals(IncomePlanCreationPhase.NeedsRecovery, retained.phase)
        assertFalse(owner.state.value.canModify)
        repo.lookupResponder = { _, _ -> Result.success(createSubmission(
            IncomePlanCreateCall(original.binding, requireNotNull(original.draft.toRepositoryDraftOrNull()), original.creationKey), 92L)) }
        owner.retryPublicationRecovery() // original acceptance can be checked by a read-only owner
        advanceUntilIdle()
        assertNull(owner.state.value.session)
        assertEquals(92L, owner.state.value.publishedRowId)
        assertTrue(repo.creationCalls.isEmpty())
    }

    @Test
    fun unsubmittedDraftRecoversAfterReadFailureWithoutLosingItsOriginalTask() = runTest(dispatcher) {
        val saved = SavedStateHandle()
        val original = retainedCreation(saved)
        val repo = FakeIncomePlanCreateRepository().apply {
            lookupResponder = { _, _ -> Result.failure(IllegalStateException("暂时无法读取原提交")) }
        }
        val owner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        assertFalse(owner.state.value.isRestoring)
        owner.updateDraftLabel("尚未核对时覆盖")
        owner.submit()
        advanceUntilIdle()
        assertEquals(original.draft.label, owner.state.value.session?.draft?.label)
        assertTrue(repo.creationCalls.isEmpty())
        repo.lookupResponder = { _, _ -> Result.success(null) }
        owner.retryPublicationRecovery()
        advanceUntilIdle()
        val recovered = assertNotNull(owner.state.value.session)
        assertEquals(original.creationKey, recovered.creationKey)
        assertEquals(original.draft, recovered.draft)
        assertEquals(IncomePlanCreationPhase.Draft, recovered.phase)
        owner.updateDraftLabel("核对后继续填写")
        owner.submit()
        advanceUntilIdle()
        assertNull(owner.state.value.session)
        assertEquals(original.creationKey, repo.creationCalls.single().creationKey)
        assertEquals("核对后继续填写", repo.creationCalls.single().draft.label)
    }

    @Test
    fun invisibleOriginalStatusesKeepRawInputInsteadOfRetiringItIntoAnEmptyRecoveryList() = runTest(dispatcher) {
        for (status in listOf(PendingMutationStatus.Unknown, PendingMutationStatus.Abandoned)) {
            val saved = SavedStateHandle()
            val original = retainedCreation(saved, IncomePlanCreationPhase.Publishing)
            val call = IncomePlanCreateCall(original.binding, requireNotNull(original.draft.toRepositoryDraftOrNull()), original.creationKey)
            val row = createSubmission(call, 97L, status)
            val repo = FakeIncomePlanCreateRepository().apply { originals[original.binding to original.creationKey] = row }
            val owner = IncomePlanCreateViewModel(repo, saved)
            advanceUntilIdle()
            assertEquals(original.creationKey, owner.state.value.session?.creationKey)
            assertEquals(original.draft, owner.state.value.session?.draft?.copy(validationError = null))
            assertEquals(IncomePlanCreationPhase.NeedsRecovery, owner.state.value.session?.phase)
            assertNull(owner.state.value.publishedRowId)
            owner.submit()
            advanceUntilIdle()
            assertEquals(row, repo.originals.values.single())
            assertTrue(repo.creationCalls.isEmpty())
        }
    }

    @Test
    fun admissionFailureSurvivesReopeningAndSavedStateUntilTheSameTaskIsAccepted() = runTest(dispatcher) {
        val saved = SavedStateHandle()
        val repo = FakeIncomePlanCreateRepository(createResult = Result.failure(IllegalStateException("存储空间不足")))
        val owner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftLabel("  保留原稿  ")
        owner.updateDraftAmount("100.00")
        val original = assertNotNull(owner.state.value.session)
        owner.submit()
        advanceUntilIdle()
        owner.openOriginal(repo)
        advanceUntilIdle()
        assertEquals(UiText.raw("存储空间不足"), owner.state.value.session?.admissionFailure?.asUiText())
        val restored = IncomePlanCreateViewModel(repo, createStateSnapshot(saved))
        advanceUntilIdle()
        assertEquals(original.creationKey, restored.state.value.session?.creationKey)
        assertEquals(original.draft, restored.state.value.session?.draft)
        assertEquals(UiText.raw("存储空间不足"), restored.state.value.session?.admissionFailure?.asUiText())
        repo.createResult = Result.success(98L)
        restored.submit()
        advanceUntilIdle()
        assertNull(restored.state.value.session)
        assertEquals(98L, restored.state.value.publishedRowId)
        assertEquals(listOf(original.creationKey, original.creationKey), repo.creationCalls.map { it.creationKey })
    }

    @Test
    fun onlyExplicitDiscardCanLeaveAMissingPublishedOriginalAndStartANewTask() = runTest(dispatcher) {
        val saved = SavedStateHandle()
        val original = retainedCreation(saved, IncomePlanCreationPhase.Publishing)
        val repo = FakeIncomePlanCreateRepository()
        val owner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        owner.cancel()
        owner.submit()
        advanceUntilIdle()
        assertEquals(original.creationKey, owner.state.value.session?.creationKey)
        assertTrue(repo.creationCalls.isEmpty())
        owner.cancel(discardUnresolved = true)
        assertNull(owner.state.value.session)
        val restored = IncomePlanCreateViewModel(repo, createStateSnapshot(saved))
        advanceUntilIdle()
        assertNull(restored.state.value.session)
        restored.openOriginal(repo)
        assertNotEquals(original.creationKey, restored.state.value.session?.creationKey)
        assertEquals("", restored.state.value.session?.draft?.label)
        assertTrue(repo.creationCalls.isEmpty())
        assertTrue(repo.originals.isEmpty())
    }

    @Test
    fun unknownSavedPublicationPhasePreservesInputAndNeverFallsBackToDraftAdmission() = runTest(dispatcher) {
        val source = SavedStateHandle()
        val original = retainedCreation(source, IncomePlanCreationPhase.Publishing)
        val raw = requireNotNull(source.get<String>("income.create.drafts")).replace("Publishing", "future_phase")
        val saved = SavedStateHandle(mapOf("income.create.drafts" to raw))
        val repo = FakeIncomePlanCreateRepository()
        val owner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        val retained = assertNotNull(owner.state.value.session)
        assertEquals(original.creationKey, retained.creationKey)
        assertEquals(original.draft, retained.draft.copy(validationError = null))
        assertEquals(IncomePlanCreationPhase.NeedsRecovery, retained.phase)
        owner.submit()
        advanceUntilIdle()
        assertTrue(repo.creationCalls.isEmpty())
        assertNull(owner.state.value.publishedRowId)
        assertEquals(original.creationKey, owner.state.value.session?.creationKey)
    }
}
