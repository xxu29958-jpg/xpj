package com.ticketbox.viewmodel

import com.ticketbox.domain.model.PendingEnrichmentOutcome
import com.ticketbox.domain.model.PendingEnrichmentTask
import com.ticketbox.domain.model.PendingUploadReceipt
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals

@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingEnrichmentObserverTest {
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
