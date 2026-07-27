package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RecurringActions
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
class RecurringViewModelTest {
    private fun recurringTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            Dispatchers.resetMain()
        }
    }

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

        fake.candidatesResult = Result.success(emptyList())
        accessFlow.value = planAccess(ownerKey = "owner-b")
        advanceUntilIdle()

        assertTrue(vm.uiState.value.candidates.isEmpty())
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

private class FakeRecurringActions(
    var itemsResult: Result<List<RecurringItem>> = Result.success(emptyList()),
    var candidatesResult: Result<List<RecurringCandidate>> = Result.success(emptyList()),
    private val canModify: Boolean = true,
    private val activeAccessFlow: Flow<LedgerAccessContext?> = flowOf(planAccess(canModify = canModify)),
) : RecurringActions {
    var confirmCalls: Int = 0
        private set
    var itemsResponder: (suspend () -> Result<List<RecurringItem>>)? = null

    override fun canModifyLedger(): Boolean = canModify

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

    override suspend fun candidates(): Result<List<RecurringCandidate>> = candidatesResult

    override suspend fun candidates(
        expectedBinding: LogicalSessionBinding,
    ): Result<List<RecurringCandidate>> = candidates()

    override suspend fun detail(publicId: String, month: String?): Result<RecurringItem> =
        Result.success(item(publicId = publicId))

    override suspend fun confirmCandidate(
        expectedBinding: LogicalSessionBinding,
        candidate: RecurringCandidate,
        nextExpectedDate: String?,
    ): Result<RecurringItem> {
        confirmCalls += 1
        return Result.success(item(merchant = candidate.merchant))
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
