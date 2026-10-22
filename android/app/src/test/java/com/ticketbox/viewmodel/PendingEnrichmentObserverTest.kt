package com.ticketbox.viewmodel

import com.ticketbox.domain.model.PendingEnrichmentOutcome
import com.ticketbox.domain.model.PendingEnrichmentTask
import com.ticketbox.domain.model.PendingUploadReceipt
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals

@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingEnrichmentObserverTest {
    @Test
    fun dismissingTerminalFeedbackKeepsAPausedTaskRetryable() = runTest {
        var online = false
        var state = PendingEnrichmentUiState()
        val requests = mutableListOf<String>()
        val observer = PendingEnrichmentObserver(this, {
            requests += it
            if (it == "paused" && !online) Result.failure(IllegalStateException("offline"))
            else Result.success(if (it == "paused") PendingEnrichmentTask("completed", PendingEnrichmentOutcome.Updated)
                else PendingEnrichmentTask("failed", null))
        }, { true }, { state = it }, {})
        observer.track(PendingUploadReceipt(1, "paused"))
        runCurrent()
        observer.track(PendingUploadReceipt(2, "failed"))
        runCurrent()
        assertEquals(PendingEnrichmentFeedbackKind.Failed, state.feedback?.kind)
        observer.dismissFeedback()
        assertEquals(PendingEnrichmentFeedback(1, PendingEnrichmentFeedbackKind.Unavailable), state.feedback)
        online = true
        observer.retryPaused()
        advanceUntilIdle()
        assertEquals(listOf("paused", "failed", "paused"), requests)
        assertEquals(PendingEnrichmentFeedback(1, PendingEnrichmentFeedbackKind.Updated), state.feedback)
    }

    @Test
    fun aPausedTaskResumesWhenItsExpenseReturnsAfterRemoval() = runTest {
        val replies = ArrayDeque(listOf(
            Result.failure<PendingEnrichmentTask>(IllegalStateException("offline")),
            Result.success(PendingEnrichmentTask("running", null)),
            Result.success(PendingEnrichmentTask("completed", PendingEnrichmentOutcome.Updated)),
        ))
        val requests = mutableListOf<String>()
        var state = PendingEnrichmentUiState()
        var refreshes = 0
        val observer = PendingEnrichmentObserver(this,
            { requests += it; replies.removeFirst() }, { true }, { state = it }, { refreshes++ })
        val receipt = PendingUploadReceipt(1, "original-task")
        observer.track(receipt)
        runCurrent()
        assertEquals(PendingEnrichmentFeedbackKind.Unavailable, state.feedback?.kind)

        observer.restore(emptyList())
        assertEquals(null, state.feedback)
        observer.retryPaused()
        runCurrent()
        assertEquals(listOf("original-task"), requests)

        observer.restore(listOf(receipt))
        advanceUntilIdle()
        assertEquals(List(3) { "original-task" }, requests)
        assertEquals(PendingEnrichmentFeedbackKind.Updated, state.feedback?.kind)
        assertEquals(0, state.activeCount)
        assertEquals(1, refreshes)
    }

    @Test
    fun dismissingOneFailureDoesNotCancelAnotherActiveRecognition() = runTest {
        val second = kotlinx.coroutines.CompletableDeferred<Result<PendingEnrichmentTask>>()
        var state = PendingEnrichmentUiState()
        val observer = PendingEnrichmentObserver(this,
            { if (it == "first") Result.success(PendingEnrichmentTask("failed", null)) else second.await() },
            { true }, { state = it }, {})
        observer.track(PendingUploadReceipt(1, "first"))
        observer.track(PendingUploadReceipt(2, "second"))
        runCurrent()
        assertEquals(1, state.activeCount)
        assertEquals(PendingEnrichmentFeedbackKind.Failed, state.feedback?.kind)
        observer.dismissFeedback()
        observer.clear(1)
        assertEquals(1, state.activeCount)
        assertEquals(null, state.feedback)
        second.complete(Result.success(PendingEnrichmentTask("completed", PendingEnrichmentOutcome.Updated)))
        advanceUntilIdle()
        assertEquals(0, state.activeCount)
        assertEquals(2L, state.feedback?.expenseId)
    }

    @Test
    fun restoredUnfinishedOutcomesStayVisibleWhileSuccessfulHistoryStaysQuiet() = runTest {
        val cases = listOf(
            PendingEnrichmentTask("completed", PendingEnrichmentOutcome.Updated) to PendingEnrichmentFeedbackKind.Updated,
            PendingEnrichmentTask("completed", PendingEnrichmentOutcome.NoResult) to PendingEnrichmentFeedbackKind.NoResult,
            PendingEnrichmentTask("completed", PendingEnrichmentOutcome.Conflict) to PendingEnrichmentFeedbackKind.Conflict,
            PendingEnrichmentTask("completed", PendingEnrichmentOutcome.NotPending) to PendingEnrichmentFeedbackKind.NotPending,
            PendingEnrichmentTask("completed", null) to PendingEnrichmentFeedbackKind.Failed,
            PendingEnrichmentTask("failed", null) to PendingEnrichmentFeedbackKind.Failed,
            PendingEnrichmentTask("cancelled", null) to PendingEnrichmentFeedbackKind.Cancelled,
        )
        for (restoring in listOf(false, true)) {
            for ((task, kind) in cases) {
                var state = PendingEnrichmentUiState()
                var fetches = 0
                var refreshes = 0
                val observer = PendingEnrichmentObserver(this, { fetches++; Result.success(task) },
                    { true }, { state = it }, { refreshes++ })
                val receipt = PendingUploadReceipt(1, "original-task")
                if (restoring) observer.restore(listOf(receipt)) else observer.track(receipt)
                advanceUntilIdle()
                val quiet = restoring && kind in setOf(PendingEnrichmentFeedbackKind.Updated, PendingEnrichmentFeedbackKind.NoResult)
                assertEquals(if (quiet) null else kind, state.feedback?.kind, "$restoring $task")
                assertEquals(if (restoring && kind == PendingEnrichmentFeedbackKind.NoResult) 0 else 1, refreshes)
                assertEquals(0, state.activeCount)
                observer.restore(listOf(receipt))
                advanceUntilIdle()
                assertEquals(1, fetches)
            }
        }
    }
}
