package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.data.repository.RecurringConflictDetails
import com.ticketbox.data.repository.RecurringDateEdit
import com.ticketbox.data.repository.RecurringItemDraft
import com.ticketbox.data.repository.RecurringItemPatch
import com.ticketbox.data.repository.RecurringLifecycleActions
import com.ticketbox.data.repository.RecurringManualMutationActions
import com.ticketbox.data.repository.RecurringPendingIntent
import com.ticketbox.data.repository.RecurringPendingKind
import com.ticketbox.data.repository.RecurringQueryActions
import com.ticketbox.data.repository.RecurringSaveOutcome
import com.ticketbox.data.repository.RepositoryConflictDetails
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.MessageTone
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
private fun recurringTest(block: suspend TestScope.() -> Unit) = runTest {
    val dispatcher = StandardTestDispatcher(testScheduler)
    Dispatchers.setMain(dispatcher)
    try {
        block()
    } finally {
        Dispatchers.resetMain()
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class RecurringViewModelTest {
    @Test
    fun initialFailureMarksBothListsFailedWithoutFabricatingEmpty() = recurringTest {
        val fake = FakeRecurringActions(
            itemsResult = Result.failure(IllegalStateException("items offline")),
            candidatesResult = Result.failure(IllegalStateException("candidates offline")),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        assertEquals(emptyList(), vm.uiState.value.items)
        assertEquals(emptyList(), vm.uiState.value.candidates)
        assertEquals(RecurringListLoadState.Failed, vm.uiState.value.itemsLoadState)
        assertEquals(RecurringListLoadState.Failed, vm.uiState.value.candidatesLoadState)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
    }

    @Test
    fun itemsLoadedEmptyAndCandidatesFailureRemainIndependent() = recurringTest {
        val fake = FakeRecurringActions(
            itemsResult = Result.success(emptyList()),
            candidatesResult = Result.failure(IllegalStateException("candidates offline")),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        assertEquals(RecurringListLoadState.Loaded, vm.uiState.value.itemsLoadState)
        assertEquals(RecurringListLoadState.Failed, vm.uiState.value.candidatesLoadState)
        assertEquals(emptyList(), vm.uiState.value.items)
        assertEquals(emptyList(), vm.uiState.value.candidates)
    }

    @Test
    fun refreshFailureKeepsExistingRowsAndMarksListsFailed() = recurringTest {
        val existingItem = item(merchant = "Cloud Storage")
        val existingCandidate = candidate("Video Plan")
        val fake = FakeRecurringActions(
            itemsResult = Result.success(listOf(existingItem)),
            candidatesResult = Result.success(listOf(existingCandidate)),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        fake.itemsResult = Result.failure(IllegalStateException("items offline"))
        fake.candidatesResult = Result.failure(IllegalStateException("candidates offline"))
        vm.refresh()
        advanceUntilIdle()

        assertEquals(listOf(existingItem), vm.uiState.value.items)
        assertEquals(listOf(existingCandidate), vm.uiState.value.candidates)
        assertEquals(RecurringListLoadState.Failed, vm.uiState.value.itemsLoadState)
        assertEquals(RecurringListLoadState.Failed, vm.uiState.value.candidatesLoadState)
    }

    @Test
    fun confirmCandidateKeepsReturnedItemWhenFollowUpRefreshFails() = recurringTest {
        val targetCandidate = candidate("Gym")
        val fake = FakeRecurringActions(
            candidatesResult = Result.success(listOf(targetCandidate)),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        fake.itemsResult = Result.failure(IllegalStateException("items offline"))
        fake.candidatesResult = Result.failure(IllegalStateException("candidates offline"))
        vm.confirmCandidate(targetCandidate)
        advanceUntilIdle()

        assertEquals(1, fake.confirmCalls)
        assertEquals(listOf(item(merchant = "Gym")), vm.uiState.value.items)
        assertEquals(emptyList(), vm.uiState.value.candidates)
        assertEquals(RecurringListLoadState.Failed, vm.uiState.value.itemsLoadState)
        assertEquals(RecurringListLoadState.Failed, vm.uiState.value.candidatesLoadState)
    }

    @Test
    fun stableAuthorityChangeClearsCandidatesAndRejectsStaleCandidate() = recurringTest {
        val accessFlow = MutableStateFlow(planAccess(ownerKey = "owner-a"))
        val oldCandidate = candidate("Old Gym")
        val fake = FakeRecurringActions(
            activeAccessFlow = accessFlow,
            candidatesResult = Result.success(listOf(oldCandidate)),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        assertEquals(listOf(oldCandidate), vm.uiState.value.candidates)
        val oldEditorEpoch = vm.uiState.value.editorEpoch

        fake.candidatesResult = Result.success(emptyList())
        accessFlow.value = planAccess(ownerKey = "owner-b")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.candidates.isEmpty())
        assertTrue(vm.uiState.value.editorEpoch > oldEditorEpoch)
        vm.confirmCandidate(oldCandidate)
        advanceUntilIdle()

        assertEquals(0, fake.confirmCalls)
        assertEquals(UiText.res(R.string.recurring_message_candidate_expired), vm.uiState.value.message)
        assertEquals(MessageTone.Info, vm.uiState.value.messageTone)
    }

    @Test
    fun staleRefreshCannotOverwriteLatestItems() = recurringTest {
        val stale = CompletableDeferred<Result<List<RecurringItem>>>()
        val latest = CompletableDeferred<Result<List<RecurringItem>>>()
        val fake = FakeRecurringActions(itemsResult = Result.success(listOf(item(merchant = "Initial"))))
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        var refreshCall = 0
        fake.itemsResponder = {
            if (++refreshCall == 1) stale.await() else latest.await()
        }

        vm.refresh()
        advanceUntilIdle()
        vm.refresh()
        advanceUntilIdle()
        latest.complete(Result.success(listOf(item(merchant = "Latest"))))
        advanceUntilIdle()
        stale.complete(Result.success(listOf(item(merchant = "Stale"))))
        advanceUntilIdle()

        assertEquals("Latest", vm.uiState.value.items.single().merchant)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class RecurringViewModelMutationTest {
    @Test
    fun queuedManualCreateIsVisibleButNeverFabricatesPublishedItem() = recurringTest {
        val pending = RecurringPendingIntent(
            kind = RecurringPendingKind.CREATE,
            targetId = "recurring_item_create:key-1",
            idempotencyKey = "key-1",
            merchant = "房租",
            baselineAmountCents = 350000,
            nextExpectedDateChanged = true,
        )
        val fake = FakeRecurringActions(
            manual = FakeRecurringManualActions(
                createResult = Result.success(RecurringSaveOutcome.Queued(pending)),
            ),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        vm.saveManual(RecurringManualSaveCommand.Create(RecurringItemDraft("房租", 350000, null)))
        advanceUntilIdle()

        assertEquals(1, fake.createCalls)
        assertEquals(emptyList(), vm.uiState.value.items)
        assertEquals(listOf(pending), vm.uiState.value.pendingIntents)
        assertEquals(UiText.res(R.string.recurring_message_queued), vm.uiState.value.message)
        assertEquals(MessageTone.Info, vm.uiState.value.messageTone)
    }

    @Test
    fun queuedManualEditKeepsObservedFactUntouched() = recurringTest {
        val observed = item(merchant = "房租").copy(
            lastAmountCents = 360000,
            occurrenceCount = 8,
            lastSeenAt = "2026-08-01T00:00:00Z",
            rowVersion = 7,
        )
        val pending = RecurringPendingIntent(
            kind = RecurringPendingKind.UPDATE,
            targetId = "recurring_item:${observed.publicId}",
            idempotencyKey = "key-2",
            publicId = observed.publicId,
            baselineAmountCents = 355000,
            nextExpectedDateChanged = true,
            nextExpectedDate = null,
        )
        val fake = FakeRecurringActions(
            itemsResult = Result.success(listOf(observed)),
            manual = FakeRecurringManualActions(
                updateResult = Result.success(RecurringSaveOutcome.Queued(pending)),
            ),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        vm.saveManual(
            RecurringManualSaveCommand.Edit(
                baseline = observed,
                patch = RecurringItemPatch(
                    baselineAmountCents = 355000,
                    nextExpectedDate = RecurringDateEdit.changed(null),
                ),
            ),
        )
        advanceUntilIdle()

        assertEquals(360000, vm.uiState.value.items.single().lastAmountCents)
        assertEquals(8, vm.uiState.value.items.single().occurrenceCount)
        assertEquals(listOf(pending), vm.uiState.value.pendingIntents)
    }

    @Test
    fun archivedRestoreCarriesTheDisplayedRowVersion() = recurringTest {
        val archived = item(publicId = "rec-archived", merchant = "旧订阅").copy(
            status = "archived",
            rowVersion = 11,
            archivedAt = "2026-08-20T00:00:00Z",
        )
        val fake = FakeRecurringActions(itemsResult = Result.success(listOf(archived)))
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        vm.restore(archived.publicId, archived.rowVersion)
        advanceUntilIdle()

        assertEquals(archived.publicId to 11L, fake.restoreCall)
    }

    @Test
    fun duplicateCreateExposesExistingArchivedItemForRestore() = recurringTest {
        val archived = item(publicId = "rec-archived", merchant = "旧订阅").copy(
            status = "archived",
            rowVersion = 11,
            archivedAt = "2026-08-20T00:00:00Z",
        )
        val conflict = RepositoryException(
            message = "这个名称已有固定支出。",
            errorCode = "recurring_item_conflict",
            conflict = RepositoryConflictDetails(
                recurring = RecurringConflictDetails(
                    publicId = archived.publicId,
                    status = archived.status,
                ),
            ),
        )
        val fake = FakeRecurringActions(
            itemsResult = Result.success(listOf(archived)),
            manual = FakeRecurringManualActions(createResult = Result.failure(conflict)),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        fake.itemsResult = Result.failure(IllegalStateException("owner refresh failed"))

        vm.saveManual(RecurringManualSaveCommand.Create(RecurringItemDraft("旧订阅", 350000, null)))
        advanceUntilIdle()

        assertEquals(
            RecurringDuplicateConflict(publicId = archived.publicId, status = "archived"),
            vm.uiState.value.duplicateConflict,
        )
        assertEquals(listOf(archived), vm.uiState.value.items)
        assertEquals(RecurringListLoadState.Failed, vm.uiState.value.itemsLoadState)
    }

    @Test
    fun duplicateCreateRefreshesAnExistingItemMissingFromTheStaleList() = recurringTest {
        val existing = item(publicId = "rec-other-device", merchant = "房租")
        val conflict = RepositoryException(
            message = "这个名称已有固定支出。",
            errorCode = "recurring_item_conflict",
            conflict = RepositoryConflictDetails(
                recurring = RecurringConflictDetails(
                    publicId = existing.publicId,
                    status = existing.status,
                ),
            ),
        )
        val fake = FakeRecurringActions(
            itemsResult = Result.success(emptyList()),
            manual = FakeRecurringManualActions(createResult = Result.failure(conflict)),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        fake.itemsResult = Result.success(listOf(existing))

        vm.saveManual(RecurringManualSaveCommand.Create(RecurringItemDraft("房租", 350000, null)))
        advanceUntilIdle()

        assertEquals(
            RecurringDuplicateConflict(publicId = existing.publicId, status = "active"),
            vm.uiState.value.duplicateConflict,
        )
        assertEquals(listOf(existing), vm.uiState.value.items)
        assertEquals(
            UiText.res(R.string.error_recurring_item_conflict),
            vm.uiState.value.message,
            "background owner refresh must not erase the failed mutation settlement",
        )
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)

        vm.refresh()
        advanceUntilIdle()

        assertEquals(
            UiText.res(R.string.error_recurring_item_conflict),
            vm.uiState.value.message,
            "a concurrent ordinary refresh must not erase an unresolved conflict",
        )
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        assertEquals(existing.publicId, vm.uiState.value.duplicateConflict?.publicId)
    }

    @Test
    fun refreshStartedBeforeManualEditCannotSettleThatEdit() = recurringTest {
        val existing = item(publicId = "rec-refresh-race", merchant = "房租")
        val staleRefresh = CompletableDeferred<Result<List<RecurringItem>>>()
        val pendingUpdate = CompletableDeferred<Result<RecurringSaveOutcome>>()
        val fake = FakeRecurringActions(itemsResult = Result.success(listOf(existing)))
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        fake.itemsResponder = { staleRefresh.await() }
        fake.updateResponder = { pendingUpdate.await() }

        vm.refresh()
        advanceUntilIdle()
        vm.saveManual(
            RecurringManualSaveCommand.Edit(existing, RecurringItemPatch(baselineAmountCents = 360000)),
        )
        advanceUntilIdle()
        staleRefresh.complete(Result.success(listOf(existing)))
        advanceUntilIdle()

        assertTrue(
            vm.uiState.value.loading,
            "a refresh started before the mutation must not settle that mutation",
        )
        pendingUpdate.complete(Result.failure(RepositoryException("update failed")))
        advanceUntilIdle()
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        assertEquals(
            RecurringListLoadState.Loaded,
            vm.uiState.value.itemsLoadState,
            "a failed save must replace the refresh it invalidated",
        )
    }

    @Test
    fun refreshStartedAfterManualEditCannotOwnThatSettlement() = recurringTest {
        val existing = item(publicId = "rec-refresh-after", merchant = "房租")
        val refreshItems = CompletableDeferred<Result<List<RecurringItem>>>()
        val pendingUpdate = CompletableDeferred<Result<RecurringSaveOutcome>>()
        val updated = existing.copy(rowVersion = 2, baselineAmountCents = 360000)
        val fake = FakeRecurringActions(itemsResult = Result.success(listOf(existing)))
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        fake.itemsResponder = { refreshItems.await() }
        fake.updateResponder = { pendingUpdate.await() }

        val attemptId = vm.saveManual(
            RecurringManualSaveCommand.Edit(existing, RecurringItemPatch(baselineAmountCents = 360000)),
        )
        advanceUntilIdle()
        vm.refresh()
        advanceUntilIdle()
        refreshItems.complete(Result.failure(IllegalStateException("refresh failed")))
        advanceUntilIdle()

        assertEquals(attemptId, vm.uiState.value.manualSaveFeedback?.attemptId)
        assertEquals(
            RecurringManualSaveSettlement.InFlight,
            vm.uiState.value.manualSaveFeedback?.settlement,
            "a later refresh failure cannot settle the editor's mutation",
        )

        pendingUpdate.complete(Result.success(RecurringSaveOutcome.Synced(updated)))
        advanceUntilIdle()

        assertEquals(attemptId, vm.uiState.value.manualSaveFeedback?.attemptId)
        assertEquals(RecurringManualSaveSettlement.Accepted, vm.uiState.value.manualSaveFeedback?.settlement)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class RecurringViewModelAttemptOwnershipTest {
    @Test
    fun manualSaveIsSingleFlightAcrossEditorReentry() = recurringTest {
        val existing = item(publicId = "rec-single-flight", merchant = "房租")
        val pendingUpdate = CompletableDeferred<Result<RecurringSaveOutcome>>()
        val updated = existing.copy(rowVersion = 2, baselineAmountCents = 360000)
        val fake = FakeRecurringActions(itemsResult = Result.success(listOf(existing)))
        fake.updateResponder = { pendingUpdate.await() }
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        val command = RecurringManualSaveCommand.Edit(
            existing,
            RecurringItemPatch(baselineAmountCents = updated.baselineAmountCents),
        )

        val firstAttempt = vm.saveManual(command)
        advanceUntilIdle()
        val reenteredAttempt = vm.saveManual(command)
        advanceUntilIdle()

        assertEquals(firstAttempt, reenteredAttempt)
        assertEquals(1, fake.updateCalls)
        assertEquals(true, vm.uiState.value.manualSaveInFlight)

        pendingUpdate.complete(Result.success(RecurringSaveOutcome.Synced(updated)))
        advanceUntilIdle()

        assertEquals(firstAttempt, vm.uiState.value.manualSaveFeedback?.attemptId)
        assertEquals(RecurringManualSaveSettlement.Accepted, vm.uiState.value.manualSaveFeedback?.settlement)
        assertEquals(false, vm.uiState.value.manualSaveInFlight)
    }

    @Test
    fun roleOnlyAccessProjectionCannotInvalidateManualSettlement() = recurringTest {
        val accessFlow = MutableStateFlow(planAccess(canModify = true))
        val existing = item(publicId = "rec-role-change", merchant = "房租")
        val pendingUpdate = CompletableDeferred<Result<RecurringSaveOutcome>>()
        val updated = existing.copy(rowVersion = 2, baselineAmountCents = 360000)
        val fake = FakeRecurringActions(
            itemsResult = Result.success(listOf(existing)),
            activeAccessFlow = accessFlow,
        )
        fake.updateResponder = { pendingUpdate.await() }
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        val attemptId = vm.saveManual(
            RecurringManualSaveCommand.Edit(
                existing,
                RecurringItemPatch(baselineAmountCents = updated.baselineAmountCents),
            ),
        )
        advanceUntilIdle()
        accessFlow.value = planAccess(canModify = false)
        advanceUntilIdle()

        assertEquals(false, vm.uiState.value.canModify)
        assertEquals(attemptId, vm.uiState.value.manualSaveFeedback?.attemptId)
        assertEquals(RecurringManualSaveSettlement.InFlight, vm.uiState.value.manualSaveFeedback?.settlement)

        pendingUpdate.complete(Result.success(RecurringSaveOutcome.Synced(updated)))
        advanceUntilIdle()

        assertEquals(attemptId, vm.uiState.value.manualSaveFeedback?.attemptId)
        assertEquals(RecurringManualSaveSettlement.Accepted, vm.uiState.value.manualSaveFeedback?.settlement)
        assertEquals(false, vm.uiState.value.canModify)
    }

    @Test
    fun queuedSaveReplacesTheRefreshItInvalidated() = recurringTest {
        val existing = item(publicId = "rec-queued-refresh", merchant = "房租")
        val refreshItems = CompletableDeferred<Result<List<RecurringItem>>>()
        val pending = RecurringPendingIntent(
            kind = RecurringPendingKind.UPDATE,
            targetId = "recurring_item:${existing.publicId}",
            idempotencyKey = "queued-refresh-key",
            publicId = existing.publicId,
            baselineAmountCents = 360000,
        )
        val fake = FakeRecurringActions(
            itemsResult = Result.success(listOf(existing)),
            manual = FakeRecurringManualActions(
                updateResult = Result.success(RecurringSaveOutcome.Queued(pending)),
            ),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        fake.itemsResponder = { refreshItems.await() }

        vm.refresh()
        advanceUntilIdle()
        vm.saveManual(
            RecurringManualSaveCommand.Edit(
                existing,
                RecurringItemPatch(baselineAmountCents = 360000),
            ),
        )
        advanceUntilIdle()
        refreshItems.complete(Result.success(listOf(existing)))
        advanceUntilIdle()

        assertEquals(RecurringListLoadState.Loaded, vm.uiState.value.itemsLoadState)
        assertEquals(RecurringListLoadState.Loaded, vm.uiState.value.candidatesLoadState)
        assertEquals(UiText.res(R.string.recurring_message_queued), vm.uiState.value.message)
        assertEquals(listOf(pending), vm.uiState.value.pendingIntents)
    }

    @Test
    fun queuedSaveWithoutDisplacedRefreshKeepsTheLoadedEmptyOwner() = recurringTest {
        val pending = RecurringPendingIntent(
            kind = RecurringPendingKind.CREATE,
            targetId = "recurring_item_create:offline-key",
            idempotencyKey = "offline-key",
            merchant = "宽带",
            baselineAmountCents = 12000,
        )
        val fake = FakeRecurringActions(
            manual = FakeRecurringManualActions(
                createResult = Result.success(RecurringSaveOutcome.Queued(pending)),
            ),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        fake.itemsResult = Result.failure(IllegalStateException("offline"))
        fake.candidatesResult = Result.failure(IllegalStateException("offline"))

        vm.saveManual(
            RecurringManualSaveCommand.Create(
                RecurringItemDraft("宽带", 12000, "2026-09-01"),
            ),
        )
        advanceUntilIdle()

        assertEquals(RecurringListLoadState.Loaded, vm.uiState.value.itemsLoadState)
        assertEquals(RecurringListLoadState.Loaded, vm.uiState.value.candidatesLoadState)
        assertEquals(UiText.res(R.string.recurring_message_queued), vm.uiState.value.message)
        assertEquals(listOf(pending), vm.uiState.value.pendingIntents)
    }

    @Test
    fun failedSaveWithoutDisplacedRefreshKeepsTheLoadedEmptyOwner() = recurringTest {
        val fake = FakeRecurringActions(
            manual = FakeRecurringManualActions(
                createResult = Result.failure(RepositoryException("save rejected")),
            ),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        fake.itemsResult = Result.failure(IllegalStateException("offline"))
        fake.candidatesResult = Result.failure(IllegalStateException("offline"))

        vm.saveManual(
            RecurringManualSaveCommand.Create(
                RecurringItemDraft("宽带", 12000, "2026-09-01"),
            ),
        )
        advanceUntilIdle()

        assertEquals(RecurringListLoadState.Loaded, vm.uiState.value.itemsLoadState)
        assertEquals(RecurringListLoadState.Loaded, vm.uiState.value.candidatesLoadState)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
    }
}

@OptIn(ExperimentalCoroutinesApi::class)
class RecurringViewModelFailureRecoveryTest {
    @Test
    fun repeatedReadonlyGuardsPublishDistinctManualAttempts() = recurringTest {
        val fake = FakeRecurringActions(activeAccessFlow = flowOf(null))
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        val draft = RecurringItemDraft("房租", 350000, null)

        val firstAttempt = vm.saveManual(RecurringManualSaveCommand.Create(draft))
        val firstFeedback = vm.uiState.value.manualSaveFeedback
        val secondAttempt = vm.saveManual(RecurringManualSaveCommand.Create(draft))
        val secondFeedback = vm.uiState.value.manualSaveFeedback

        assertTrue(secondAttempt > firstAttempt)
        assertEquals(firstAttempt, firstFeedback?.attemptId)
        assertEquals(secondAttempt, secondFeedback?.attemptId)
        assertEquals(RecurringManualSaveSettlement.Failed, secondFeedback?.settlement)
    }

    @Test
    fun stateConflictRefreshesTheOwnerWithoutErasingTheFailure() = recurringTest {
        val stale = item(publicId = "rec-stale-edit", merchant = "房租")
        val fresh = stale.copy(rowVersion = stale.rowVersion + 1, baselineAmountCents = 360000)
        val conflict = RepositoryException(message = "版本冲突", errorCode = "state_conflict")
        val fake = FakeRecurringActions(
            itemsResult = Result.success(listOf(stale)),
            manual = FakeRecurringManualActions(updateResult = Result.failure(conflict)),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        fake.itemsResult = Result.success(listOf(fresh))

        vm.saveManual(
            RecurringManualSaveCommand.Edit(stale, RecurringItemPatch(baselineAmountCents = 370000)),
        )
        advanceUntilIdle()

        assertEquals(listOf(fresh), vm.uiState.value.items)
        assertEquals(UiText.raw("版本冲突"), vm.uiState.value.message)
        assertEquals(MessageTone.Danger, vm.uiState.value.messageTone)
        assertEquals(RecurringListLoadState.Loaded, vm.uiState.value.itemsLoadState)
        assertEquals(true, vm.uiState.value.manualSaveFeedback?.requiresOwnerReload)

        vm.refresh()
        advanceUntilIdle()

        assertEquals(null, vm.uiState.value.message)
        assertEquals(MessageTone.Neutral, vm.uiState.value.messageTone)
        assertEquals(
            true,
            vm.uiState.value.manualSaveFeedback?.requiresOwnerReload,
            "ordinary page refresh clears stale copy without stealing the editor's conflict receipt",
        )
    }

    @Test
    fun duplicateCreateRefreshesAnExistingItemWhoseStatusBecameArchived() = recurringTest {
        val stale = item(publicId = "rec-other-device", merchant = "房租")
        val archived = stale.copy(
            status = "archived",
            rowVersion = stale.rowVersion + 1,
            archivedAt = "2026-08-30T00:00:00Z",
        )
        val conflict = RepositoryException(
            message = "这条固定支出已归档。",
            errorCode = "recurring_item_conflict",
            conflict = RepositoryConflictDetails(
                recurring = RecurringConflictDetails(
                    publicId = archived.publicId,
                    status = archived.status,
                ),
            ),
        )
        val fake = FakeRecurringActions(
            itemsResult = Result.success(listOf(stale)),
            manual = FakeRecurringManualActions(createResult = Result.failure(conflict)),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()
        fake.itemsResult = Result.success(listOf(archived))

        vm.saveManual(RecurringManualSaveCommand.Create(RecurringItemDraft("房租", 350000, null)))
        advanceUntilIdle()

        assertEquals(listOf(archived), vm.uiState.value.items)
        assertEquals("archived", vm.uiState.value.duplicateConflict?.status)
    }

    @Test
    fun staleCandidateConflictExposesExistingArchivedItemForRestore() = recurringTest {
        val archived = item(publicId = "rec-archived", merchant = "旧订阅").copy(
            status = "archived",
            rowVersion = 11,
            archivedAt = "2026-08-20T00:00:00Z",
        )
        val staleCandidate = candidate("旧订阅")
        val conflict = RepositoryException(
            message = "固定支出已归档。",
            errorCode = "recurring_item_archived",
            conflict = RepositoryConflictDetails(
                recurring = RecurringConflictDetails(
                    publicId = archived.publicId,
                    status = archived.status,
                ),
            ),
        )
        val fake = FakeRecurringActions(
            itemsResult = Result.success(listOf(archived)),
            candidatesResult = Result.success(listOf(staleCandidate)),
            lifecycle = FakeRecurringLifecycleActions(confirmResult = Result.failure(conflict)),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        vm.confirmCandidate(staleCandidate)
        advanceUntilIdle()

        assertEquals(
            RecurringDuplicateConflict(publicId = archived.publicId, status = "archived"),
            vm.uiState.value.duplicateConflict,
        )
    }
}

private class FakeRecurringActions private constructor(
    private val queryDelegate: FakeRecurringQueryActions,
    private val manual: FakeRecurringManualActions = FakeRecurringManualActions(),
    private val lifecycle: FakeRecurringLifecycleActions = FakeRecurringLifecycleActions(),
) : RecurringActions,
    RecurringQueryActions by queryDelegate,
    RecurringManualMutationActions by manual,
    RecurringLifecycleActions by lifecycle {
    constructor(
        itemsResult: Result<List<RecurringItem>> = Result.success(emptyList()),
        candidatesResult: Result<List<RecurringCandidate>> = Result.success(emptyList()),
        activeAccessFlow: Flow<LedgerAccessContext?> = flowOf(planAccess()),
        manual: FakeRecurringManualActions = FakeRecurringManualActions(),
        lifecycle: FakeRecurringLifecycleActions = FakeRecurringLifecycleActions(),
    ) : this(
        queryDelegate = FakeRecurringQueryActions(itemsResult, candidatesResult, activeAccessFlow),
        manual = manual,
        lifecycle = lifecycle,
    )

    var itemsResult: Result<List<RecurringItem>>
        get() = queryDelegate.itemsResult
        set(value) { queryDelegate.itemsResult = value }
    var candidatesResult: Result<List<RecurringCandidate>>
        get() = queryDelegate.candidatesResult
        set(value) { queryDelegate.candidatesResult = value }
    var itemsResponder: (suspend () -> Result<List<RecurringItem>>)?
        get() = queryDelegate.itemsResponder
        set(value) { queryDelegate.itemsResponder = value }
    var updateResponder: (suspend () -> Result<RecurringSaveOutcome>)?
        get() = manual.updateResponder
        set(value) { manual.updateResponder = value }
    val updateCalls: Int get() = manual.updateCalls
    val confirmCalls: Int get() = lifecycle.confirmCalls
    val createCalls: Int get() = manual.createCalls
    val restoreCall: Pair<String, Long>? get() = lifecycle.restoreCall
}

private class FakeRecurringQueryActions(
    var itemsResult: Result<List<RecurringItem>>,
    var candidatesResult: Result<List<RecurringCandidate>>,
    private val activeAccessFlow: Flow<LedgerAccessContext?>,
) : RecurringQueryActions {
    var itemsResponder: (suspend () -> Result<List<RecurringItem>>)? = null

    override fun canModifyLedger(): Boolean = true
    override fun observeActiveLedgerAccess(): Flow<LedgerAccessContext?> = activeAccessFlow
    override suspend fun items(
        status: String?,
        includeArchived: Boolean,
        month: String?,
    ): Result<List<RecurringItem>> = itemsResponder?.invoke() ?: itemsResult
    override suspend fun items(
        expectedBinding: LogicalSessionBinding,
        status: String?,
        includeArchived: Boolean,
        month: String?,
    ): Result<List<RecurringItem>> = items(status, includeArchived, month)
    override suspend fun candidates(
        expectedBinding: LogicalSessionBinding,
    ): Result<List<RecurringCandidate>> = candidatesResult
}

private class FakeRecurringManualActions(
    var createResult: Result<RecurringSaveOutcome> = Result.failure(IllegalStateException("create not configured")),
    var updateResult: Result<RecurringSaveOutcome> = Result.failure(IllegalStateException("update not configured")),
    private val pendingIntentsFlow: Flow<List<RecurringPendingIntent>> = flowOf(emptyList()),
) : RecurringManualMutationActions {
    var updateResponder: (suspend () -> Result<RecurringSaveOutcome>)? = null
    var createCalls: Int = 0
        private set
    var updateCalls: Int = 0
        private set

    override fun observePendingIntents(): Flow<List<RecurringPendingIntent>> = pendingIntentsFlow
    override suspend fun createAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        draft: RecurringItemDraft,
    ): Result<RecurringSaveOutcome> {
        createCalls += 1
        return createResult
    }
    override suspend fun updateAllowingOffline(
        expectedBinding: LogicalSessionBinding,
        baseline: RecurringItem,
        patch: RecurringItemPatch,
    ): Result<RecurringSaveOutcome> {
        updateCalls += 1
        return updateResponder?.invoke() ?: updateResult
    }
}

private class FakeRecurringLifecycleActions(
    var confirmResult: Result<RecurringItem>? = null,
) : RecurringLifecycleActions {
    var confirmCalls: Int = 0
        private set
    var restoreCall: Pair<String, Long>? = null
        private set

    override suspend fun confirmCandidate(
        expectedBinding: LogicalSessionBinding,
        candidate: RecurringCandidate,
        nextExpectedDate: String?,
    ): Result<RecurringItem> {
        confirmCalls += 1
        return confirmResult ?: Result.success(item(merchant = candidate.merchant))
    }
    override suspend fun pause(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem> = Result.success(item(publicId = publicId))
    override suspend fun resume(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem> = Result.success(item(publicId = publicId))
    override suspend fun archive(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
    ): Result<RecurringItem> = Result.success(item(publicId = publicId))
    override suspend fun restore(
        expectedBinding: LogicalSessionBinding,
        publicId: String,
        expectedRowVersion: Long,
    ): Result<RecurringItem> {
        restoreCall = publicId to expectedRowVersion
        return Result.success(item(publicId = publicId))
    }
}

private fun planBinding(
    ledgerId: String = "owner",
    ownerKey: String = "owner",
): LogicalSessionBinding = LogicalSessionBinding(
    serverUrl = "https://api.example.com",
    ledgerId = ledgerId,
    ownerKey = ownerKey,
    sessionGeneration = "session-$ownerKey",
    bindingRevision = "binding-$ownerKey-$ledgerId",
)

private fun planAccess(
    ledgerId: String = "owner",
    ownerKey: String = "owner",
    canModify: Boolean = true,
): LedgerAccessContext = LedgerAccessContext(
    binding = planBinding(ledgerId, ownerKey),
    canModify = canModify,
)

private fun candidate(merchant: String): RecurringCandidate = RecurringCandidate(
    merchant = merchant,
    amountCents = 9900,
    occurrenceCount = 3,
    lastSeenAt = "2026-05-01T00:00:00Z",
    confidence = "high",
    reason = "monthly",
)

private fun item(
    publicId: String = "rec-1",
    merchant: String = "Old Gym",
): RecurringItem = RecurringItem(
    publicId = publicId,
    ledgerId = "owner",
    merchant = merchant,
    merchantKey = merchant.lowercase(),
    frequency = "monthly",
    baselineAmountCents = 9900,
    lastAmountCents = 9900,
    occurrenceCount = 3,
    lastSeenAt = "2026-05-01T00:00:00Z",
    nextExpectedDate = "2026-06-01",
    status = "active",
    confidence = "high",
    source = "candidate",
    anomalyStatus = "normal",
    currentMonthAmountCents = null,
    historicalAverageAmountCents = null,
    amountDeltaPercent = null,
    createdAt = "2026-05-01T00:00:00Z",
    updatedAt = "2026-05-01T00:00:00Z",
    rowVersion = 1L,
    pausedAt = null,
    archivedAt = null,
)
