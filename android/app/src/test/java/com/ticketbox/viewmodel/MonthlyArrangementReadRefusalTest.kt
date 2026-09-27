package com.ticketbox.viewmodel

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.*
import com.ticketbox.data.repository.*
import com.ticketbox.domain.model.BudgetAdvice
import com.ticketbox.domain.model.BudgetAdviceResult
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.*

class MonthlyArrangementReadRefusalTest {
    @Test fun refusedReadClearsQueriesButKeepsTheUnsentOriginalAndAcceptedSubmission() = budgetTest {
        for (status in listOf(401, 403)) {
            val fixture = ArrangementReadFixture()
            val vm = BudgetAdviceViewModel(fixture.repository, initialMonth = "2026-09")
            advanceUntilIdle()
            vm.loadArrangementHistory()
            advanceUntilIdle()
            assertNotNull(vm.uiState.value.arrangementRead)
            assertEquals(1, vm.uiState.value.arrangementHistory.size)
            vm.editArrangement(true, "2400")
            vm.editArrangement(false, "700")
            advanceUntilIdle()
            val original = assertNotNull(vm.uiState.value.arrangementDraft)
            val submission = vm.uiState.value.arrangementPending.single()
            fixture.readFailure = RepositoryException("Access refused", httpStatusCode = status)
            vm.refreshArrangement()
            advanceUntilIdle()
            assertNull(vm.uiState.value.arrangementRead)
            assertTrue(vm.uiState.value.arrangementHistory.isEmpty())
            assertFalse(vm.uiState.value.arrangementHistoryLoaded)
            assertNull(vm.uiState.value.inputs)
            assertNull(vm.uiState.value.result)
            assertEquals(original, vm.uiState.value.arrangementDraft)
            assertEquals(original, fixture.draft)
            fixture.pending.value = emptyList()
            advanceUntilIdle()
            fixture.pending.value = listOf(submission)
            advanceUntilIdle()
            assertNull(vm.uiState.value.arrangementRead)
            assertEquals(submission, vm.uiState.value.arrangementPending.single())
            assertEquals(original, fixture.draft)
        }
    }

    @Test fun historyRefusalRejectsEarlierReadAndCachedAdviceCompletion() = budgetTest {
        val fixture = ArrangementReadFixture()
        val cached = CompletableDeferred<BudgetAdviceResult?>()
        fixture.cachedAdvice = cached
        val vm = BudgetAdviceViewModel(fixture.repository, initialMonth = "2026-09")
        advanceUntilIdle()
        vm.loadArrangementHistory()
        advanceUntilIdle()
        val inputs = assertNotNull(vm.uiState.value.inputs)
        val earlierRead = CompletableDeferred<Result<MonthlyArrangementRead>>()
        fixture.delayedRead = earlierRead
        vm.refreshArrangement()
        advanceUntilIdle()
        assertTrue(vm.uiState.value.arrangementLoading)
        fixture.historyFailure = RepositoryException("Access refused", httpStatusCode = 403)
        vm.loadArrangementHistory()
        advanceUntilIdle()
        assertNull(vm.uiState.value.arrangementRead)
        assertTrue(vm.uiState.value.arrangementHistory.isEmpty())
        earlierRead.complete(Result.success(fixture.read))
        cached.complete(BudgetAdviceResult(BudgetAdvice("Old accepted advice", emptyList(), null), "JPY", "fixture", null, inputs))
        advanceUntilIdle()
        assertNull(vm.uiState.value.arrangementRead)
        assertTrue(vm.uiState.value.arrangementHistory.isEmpty())
        assertNull(vm.uiState.value.inputs)
        assertNull(vm.uiState.value.result)
        assertFalse(vm.uiState.value.arrangementLoading)
        assertFalse(vm.uiState.value.arrangementBusy)
    }
}

private class ArrangementReadFixture {
    private val base = FakeBudgetActions(budget())
    private val fact = MonthlyArrangementDto("owner", "2026-09", "JPY", 1200, 300, 1, "2026-09-27T00:00:00Z")
    val read = MonthlyArrangementRead(MonthlyArrangementResponseDto("owner", "2026-09", fact))
    var draft: MonthlyArrangementDraft? = null
    var readFailure: Throwable? = null
    var historyFailure: Throwable? = null
    var delayedRead: CompletableDeferred<Result<MonthlyArrangementRead>>? = null
    var cachedAdvice: CompletableDeferred<BudgetAdviceResult?>? = null
    private val row = OutboxRow(id = 1, serverUrl = "https://example.test", ledgerId = "owner",
        type = PendingMutationType.SaveMonthlyArrangement, targetId = "monthly_arrangement:2026-09",
        payloadJson = "original payload", expectedRowVersion = 0, status = PendingMutationStatus.Done,
        retryCount = 0, lastError = null, createdAt = fact.updatedAt, attemptedAt = fact.updatedAt,
        completedAt = fact.updatedAt, idempotencyKey = "original-key", receiptJson = "original receipt")
    val pending = MutableStateFlow(listOf(PendingMonthlyArrangement(row,
        MonthlyArrangementPayload(1, fact.month, MonthlyArrangementSaveRequest("JPY", 1200, 300)), fact)))
    val repository: BudgetActions = object : BudgetActions by base {
        override suspend fun arrangement(binding: LogicalSessionBinding, month: String): Result<MonthlyArrangementRead> =
            delayedRead?.await() ?: readFailure?.let { Result.failure(it) } ?: Result.success(read)
        override suspend fun arrangementHistory(binding: LogicalSessionBinding, month: String, beforeVersion: Long?): Result<MonthlyArrangementHistoryRead> =
            historyFailure?.let { Result.failure(it) } ?: Result.success(MonthlyArrangementHistoryRead(
                MonthlyArrangementHistoryDto(binding.ledgerId, month,
                    listOf(MonthlyArrangementHistoryItemDto(1, fact.updatedAt, "JPY", 1200, 300)), null)))
        override suspend fun arrangementDraft(binding: LogicalSessionBinding, month: String) = draft
        override suspend fun storeArrangementDraft(binding: LogicalSessionBinding, month: String, draft: MonthlyArrangementDraft) {
            this@ArrangementReadFixture.draft = draft
        }
        override fun observeArrangements(binding: LogicalSessionBinding) = pending
        override suspend fun cachedBudgetAdvice(month: String, homeCurrencyCode: String?) = cachedAdvice?.await()
    }
}
