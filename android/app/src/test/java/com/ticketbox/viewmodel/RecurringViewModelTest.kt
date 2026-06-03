package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RecurringActions
import com.ticketbox.domain.model.RecurringCandidate
import com.ticketbox.domain.model.RecurringItem
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.emptyFlow
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
    fun activeLedgerChangeClearsCandidatesAndRejectsStaleCandidate() = recurringTest {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val oldCandidate = candidate("Old Gym")
        val fake = FakeRecurringActions(
            activeLedgerFlow = ledgerFlow,
            candidatesResult = Result.success(listOf(oldCandidate)),
        )
        val vm = RecurringViewModel(fake)
        advanceUntilIdle()

        assertEquals(listOf(oldCandidate), vm.uiState.value.candidates)

        fake.candidatesResult = Result.success(emptyList())
        ledgerFlow.value = "family"
        advanceUntilIdle()

        assertTrue(vm.uiState.value.candidates.isEmpty())
        vm.confirmCandidate(oldCandidate)
        advanceUntilIdle()

        assertEquals(0, fake.confirmCalls)
        assertTrue(vm.uiState.value.message?.contains("已过期") == true)
    }
}

private class FakeRecurringActions(
    private val activeLedgerFlow: Flow<String?> = emptyFlow(),
    var itemsResult: Result<List<RecurringItem>> = Result.success(emptyList()),
    var candidatesResult: Result<List<RecurringCandidate>> = Result.success(emptyList()),
    private val canModify: Boolean = true,
) : RecurringActions {
    var confirmCalls: Int = 0
        private set

    override fun canModifyLedger(): Boolean = canModify

    override fun observeActiveLedgerId(): Flow<String?> = activeLedgerFlow

    override suspend fun items(
        status: String?,
        includeArchived: Boolean,
        month: String?,
    ): Result<List<RecurringItem>> = itemsResult

    override suspend fun candidates(): Result<List<RecurringCandidate>> = candidatesResult

    override suspend fun detail(publicId: String, month: String?): Result<RecurringItem> =
        Result.success(item(publicId = publicId))

    override suspend fun confirmCandidate(
        candidate: RecurringCandidate,
        nextExpectedDate: String?,
    ): Result<RecurringItem> {
        confirmCalls += 1
        return Result.success(item(merchant = candidate.merchant))
    }

    override suspend fun pause(publicId: String, expectedRowVersion: Long): Result<RecurringItem> = Result.success(item(publicId = publicId))

    override suspend fun resume(publicId: String, expectedRowVersion: Long): Result<RecurringItem> = Result.success(item(publicId = publicId))

    override suspend fun archive(publicId: String): Result<RecurringItem> = Result.success(item(publicId = publicId))
}

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
