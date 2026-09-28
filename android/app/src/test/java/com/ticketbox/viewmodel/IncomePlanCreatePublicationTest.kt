package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.domain.model.CurrencyCode
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
import kotlin.test.assertNotEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class IncomePlanCreatePublicationTest {
    private val dispatcher = StandardTestDispatcher()
    @BeforeTest fun setup() { Dispatchers.setMain(dispatcher) }
    @AfterTest fun tearDown() { Dispatchers.resetMain() }

    @Test
    fun lateAcceptanceRetiresOnlyItsOriginalTaskAndKeepsAnotherIdentityDraft() = runTest(dispatcher) {
        val gate = CompletableDeferred<Result<Long>>()
        val saved = SavedStateHandle()
        val repo = FakeIncomePlanCreateRepository().apply { createResponder = { gate.await() } }
        val owner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftLabel("原身份工资")
        owner.updateDraftAmount("1200")
        val original = assertNotNull(owner.state.value.session)
        owner.submit()
        advanceUntilIdle()
        assertTrue(owner.state.value.isSubmitting)
        assertEquals(IncomePlanCreationPhase.Publishing, owner.state.value.session?.phase)
        val nextBinding = original.binding.copy(ledgerId = "family", ownerKey = "family-owner")
        repo.activeAccessFlow.value = LedgerAccessContext(nextBinding, canModify = true)
        advanceUntilIdle()
        owner.open(nextBinding, "2026-10", CurrencyCode.JPY)
        owner.updateDraftLabel("下一身份收入")
        owner.updateDraftAmount("987")
        val next = assertNotNull(owner.state.value.session)
        gate.complete(Result.success(51L))
        advanceUntilIdle()
        assertEquals(next, owner.state.value.session)
        assertNull(owner.state.value.publishedRowId)
        assertNull(owner.state.value.flashMessage)
        assertFalse(owner.state.value.isSubmitting)
        val reconstructed = IncomePlanCreateViewModel(repo, createStateSnapshot(saved))
        advanceUntilIdle()
        assertEquals(next, reconstructed.state.value.session)
        repo.activeAccessFlow.value = LedgerAccessContext(original.binding, canModify = true)
        advanceUntilIdle()
        assertNull(owner.state.value.session)
        assertNull(reconstructed.state.value.session)
        val accepted = assertNotNull(repo.originals[original.binding to original.creationKey])
        assertEquals(51L, accepted.row.id)
        assertEquals("原身份工资", accepted.intent?.originalLabel)
        assertNull(accepted.confirmed)
    }

    @Test
    fun permissionChangeAndSheetReentryCannotChangePublishingInputOrStartAnotherCommand() = runTest(dispatcher) {
        val gate = CompletableDeferred<Result<Long>>()
        val repo = FakeIncomePlanCreateRepository().apply { createResponder = { gate.await() } }
        val owner = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftLabel("原稿")
        owner.updateDraftAmount("100")
        owner.submit()
        advanceUntilIdle()
        val publishing = assertNotNull(owner.state.value.session)
        repo.activeAccessFlow.value = requireNotNull(repo.activeAccessFlow.value).copy(canModify = false)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftAmount("999")
        owner.cancel()
        owner.submit()
        assertEquals(publishing, owner.state.value.session)
        assertTrue(owner.state.value.isSubmitting)
        gate.complete(Result.success(52L))
        advanceUntilIdle()
        assertNull(owner.state.value.session)
        assertEquals(52L, owner.state.value.publishedRowId)
        assertEquals(10_000L, repo.creationCalls.single().draft.amountCents)
    }

    @Test
    fun knownFailedAdmissionRetainsRawInputAndRetriesTheSameOriginalKey() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository(createResult = Result.failure(IllegalStateException("Room拒绝")))
        val owner = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        owner.openOriginal(repo)
        owner.updateDraftLabel("  原稿  ")
        owner.updateDraftAmount("100.00")
        val original = assertNotNull(owner.state.value.session)
        owner.submit()
        advanceUntilIdle()
        assertNull(owner.state.value.publishedRowId)
        assertEquals(IncomePlanCreationPhase.Draft, owner.state.value.session?.phase)
        assertEquals(original.creationKey, owner.state.value.session?.creationKey)
        assertEquals("  原稿  ", owner.state.value.session?.draft?.label)
        assertEquals("100.00", owner.state.value.session?.draft?.amountYuanInput)
        assertEquals(UiText.raw("Room拒绝"), owner.state.value.session?.draft?.validationError)
        repo.createResult = Result.success(53L)
        owner.submit()
        advanceUntilIdle()
        assertEquals(listOf(original.creationKey, original.creationKey), repo.creationCalls.map { it.creationKey })
        assertEquals(repo.creationCalls.first().draft, repo.creationCalls.last().draft)
        assertEquals(53L, owner.state.value.publishedRowId)
        assertNull(owner.state.value.session)
    }

    @Test
    fun uncertainPublishingSnapshotWithMissingOriginalNeverAutomaticallyCreatesAnotherCommand() = runTest(dispatcher) {
        val saved = SavedStateHandle()
        val repo = FakeIncomePlanCreateRepository()
        val original = retainedCreation(saved, phase = IncomePlanCreationPhase.Publishing)
        val owner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        val unresolved = assertNotNull(owner.state.value.session)
        assertEquals(original.creationKey, unresolved.creationKey)
        assertEquals(original.draft, unresolved.draft.copy(validationError = null))
        assertEquals(IncomePlanCreationPhase.NeedsRecovery, unresolved.phase)
        assertEquals(UiText.res(R.string.income_plan_creation_recovery_required), unresolved.draft.validationError)
        owner.submit()
        advanceUntilIdle()
        owner.cancel()
        owner.updateDraftAmount("999")
        assertEquals(unresolved, owner.state.value.session)
        assertNull(owner.state.value.publishedRowId)
        assertTrue(repo.creationCalls.isEmpty())
        assertEquals(listOf(original.binding to original.creationKey, original.binding to original.creationKey), repo.lookups)
        val afterRecreation = IncomePlanCreateViewModel(repo, createStateSnapshot(saved))
        advanceUntilIdle()
        assertEquals(unresolved, afterRecreation.state.value.session)
    }

    @Test
    fun everyRetainedOriginalStatusSettlesItsKeyWithoutInventingConfirmedFinancialFacts() = runTest(dispatcher) {
        for (status in PendingMutationStatus.entries) {
            val saved = SavedStateHandle()
            val original = retainedCreation(saved, phase = IncomePlanCreationPhase.Publishing)
            val repo = FakeIncomePlanCreateRepository()
            val call = IncomePlanCreateCall(original.binding, requireNotNull(original.draft.toRepositoryDraftOrNull()), original.creationKey)
            repo.originals[original.binding to original.creationKey] = createSubmission(call, 61L, status)
            val owner = IncomePlanCreateViewModel(repo, saved)
            advanceUntilIdle()
            assertNull(owner.state.value.session)
            assertEquals(61L, owner.state.value.publishedRowId)
            owner.submit()
            assertTrue(repo.creationCalls.isEmpty())
            assertTrue(repo.active.plans.isEmpty())
            assertNull(repo.originals.values.single().confirmed)
            val reconstructed = IncomePlanCreateViewModel(repo, createStateSnapshot(saved))
            advanceUntilIdle()
            assertNull(reconstructed.state.value.session)
            assertNull(reconstructed.state.value.publishedRowId)
        }
    }

    @Test
    fun olderDraftSnapshotSettlesItsOriginalKeyEvenWhenRoomHasTheLaterEditedBody() = runTest(dispatcher) {
        val saved = SavedStateHandle()
        val original = retainedCreation(saved)
        val laterDraft = requireNotNull(original.draft.copy(label = "稍后确认稿", amountYuanInput = "200").toRepositoryDraftOrNull())
        val repo = FakeIncomePlanCreateRepository()
        repo.originals[original.binding to original.creationKey] = createSubmission(
            IncomePlanCreateCall(original.binding, laterDraft, original.creationKey), 71L, PendingMutationStatus.Done)
        val owner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        assertNull(owner.state.value.session)
        assertEquals(71L, owner.state.value.publishedRowId)
        assertEquals(listOf(original.binding to original.creationKey), repo.lookups)
        assertTrue(repo.creationCalls.isEmpty())
        assertEquals("稍后确认稿", repo.originals.values.single().intent?.originalLabel)
        assertNull(repo.originals.values.single().confirmed)
    }

    @Test
    fun distinctNewKeysAllowAnIntentionallyRepeatedBody() = runTest(dispatcher) {
        val repo = FakeIncomePlanCreateRepository().apply { createResponder = { Result.success(80L + createCalls) } }
        val owner = IncomePlanCreateViewModel(repo)
        advanceUntilIdle()
        repeat(2) {
            owner.openOriginal(repo)
            owner.updateDraftLabel("相同收入")
            owner.updateDraftAmount("100")
            owner.submit()
            advanceUntilIdle()
            assertEquals(81L + it, owner.state.value.publishedRowId)
            assertNull(owner.state.value.session)
            owner.consumePublished()
        }
        val calls = repo.creationCalls
        assertEquals(calls.first().draft, calls.last().draft)
        assertNotEquals(calls.first().creationKey, calls.last().creationKey)
        assertEquals(2, repo.originals.size)
    }

    @Test
    fun lateAcknowledgementCannotDeleteANewerTaskUnderTheSameCompleteBinding() = runTest(dispatcher) {
        val gate = CompletableDeferred<Result<Long>>()
        val saved = SavedStateHandle()
        val repo = FakeIncomePlanCreateRepository().apply {
            createResponder = { call ->
                originals[call.binding to call.creationKey] = createSubmission(call, 101L)
                gate.await() // Room accepted the original before its UI acknowledgement returns
            }
        }
        val oldOwner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        oldOwner.openOriginal(repo)
        oldOwner.updateDraftLabel("已经保存的原稿")
        oldOwner.updateDraftAmount("100")
        val original = assertNotNull(oldOwner.state.value.session)
        oldOwner.submit()
        advanceUntilIdle()
        val currentOwner = IncomePlanCreateViewModel(repo, saved)
        advanceUntilIdle()
        assertEquals(101L, currentOwner.state.value.publishedRowId)
        assertNull(currentOwner.state.value.session)
        currentOwner.consumePublished()
        currentOwner.openOriginal(repo)
        currentOwner.updateDraftLabel("同身份新任务")
        currentOwner.updateDraftAmount("200")
        val newer = assertNotNull(currentOwner.state.value.session)
        assertNotEquals(original.creationKey, newer.creationKey)
        gate.complete(Result.success(101L))
        advanceUntilIdle()
        assertEquals(newer, currentOwner.state.value.session)
        assertNull(currentOwner.state.value.publishedRowId)
        val reconstructed = IncomePlanCreateViewModel(repo, createStateSnapshot(saved))
        advanceUntilIdle()
        assertEquals(newer, reconstructed.state.value.session)
        assertEquals("同身份新任务", reconstructed.state.value.session?.draft?.label)
        assertEquals("200", reconstructed.state.value.session?.draft?.amountYuanInput)
        assertEquals(original.creationKey, repo.creationCalls.single().creationKey)
    }
}

internal fun retainedCreation(saved: SavedStateHandle,
    phase: IncomePlanCreationPhase = IncomePlanCreationPhase.Draft): IncomePlanCreateSession {
    val session = IncomePlanCreateSession(editBinding(), "original-creation-key",
        IncomePlanDraftUi(intentMonth = "2026-09", incomeMonthInput = "2026-08", label = "  原稿  ",
            amountYuanInput = "100.00", payDayInput = "09", homeCurrency = CurrencyCode.CNY), phase)
    IncomePlanCreateDraftStore(saved).write(session)
    return session
}
