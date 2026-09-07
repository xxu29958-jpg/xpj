package com.ticketbox.viewmodel

import com.ticketbox.domain.model.PendingEnrichmentOutcome
import com.ticketbox.domain.model.PendingEnrichmentTask
import com.ticketbox.data.local.PendingMutationStatus
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelEnrichmentTest : PendingViewModelReviewTestBase() {

    @Test
    fun completedEnrichmentRefreshesTheInitiatingPendingConsumer() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(
            activeLedgerFlow = ledgerFlow,
            activeLedgerIdProvider = { ledgerFlow.value },
        )
        var taskFetches = 0
        fake.enrichmentTasks.responder = {
            taskFetches += 1
            if (taskFetches == 1) {
                Result.success(task(status = "queued"))
            } else {
                fake.pending = listOf(expense(id = 7L, merchant = "识别后的商家"))
                Result.success(task(status = "completed", outcome = PendingEnrichmentOutcome.Updated))
            }
        }
        val vm = pendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks)
        advanceUntilIdle()

        fake.uploadIntents.publish(observedUpload(7, PendingMutationStatus.Done, binding = fake.uploadIntents.currentBinding))
        runCurrent()
        advanceUntilIdle()

        assertEquals(2, fake.enrichmentTasks.calls)
        assertEquals(listOf("task-7", "task-7"), fake.enrichmentTasks.fetchedTaskIds)
        assertEquals("识别后的商家", vm.uiState.value.items.single().merchant)
        assertEquals(0, vm.uiState.value.enrichment.activeCount)
        assertEquals(PendingEnrichmentFeedbackKind.Updated, vm.uiState.value.enrichment.feedback?.kind)
        assertNull(vm.uiState.value.message)
    }

    @Test
    fun unavailableObservationPausesUntilTheUserRetries() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(
            activeLedgerFlow = ledgerFlow,
            activeLedgerIdProvider = { ledgerFlow.value },
        )
        var taskFetches = 0
        fake.enrichmentTasks.responder = {
            taskFetches += 1
            if (taskFetches == 1) {
                Result.failure(IllegalStateException("offline"))
            } else {
                Result.success(task(status = "completed", outcome = PendingEnrichmentOutcome.NoResult))
            }
        }
        val vm = pendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks)
        advanceUntilIdle()

        fake.uploadIntents.publish(observedUpload(8, PendingMutationStatus.Done, binding = fake.uploadIntents.currentBinding))
        runCurrent()
        advanceUntilIdle()

        assertEquals(1, fake.enrichmentTasks.calls)
        assertEquals(PendingEnrichmentFeedbackKind.Unavailable, vm.uiState.value.enrichment.feedback?.kind)
        assertEquals(0, vm.uiState.value.enrichment.activeCount)

        vm.retryEnrichmentObservation()
        advanceUntilIdle()

        assertEquals(2, fake.enrichmentTasks.calls)
        assertEquals(PendingEnrichmentFeedbackKind.NoResult, vm.uiState.value.enrichment.feedback?.kind)
    }

    @Test
    fun ledgerSwitchCancelsTheOldLedgerObservationAndClearsItsStatus() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val taskResponse = CompletableDeferred<Result<PendingEnrichmentTask>>()
        val fake = FakeReviewActions(
            activeLedgerFlow = ledgerFlow,
            activeLedgerIdProvider = { ledgerFlow.value },
        )
        fake.enrichmentTasks.responder = { taskResponse.await() }
        val vm = pendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks)
        advanceUntilIdle()

        fake.uploadIntents.publish(observedUpload(9, PendingMutationStatus.Done, binding = fake.uploadIntents.currentBinding))
        runCurrent()
        runCurrent()
        assertEquals(1, vm.uiState.value.enrichment.activeCount)

        ledgerFlow.value = "family"
        runCurrent()
        taskResponse.complete(Result.success(task(status = "completed", outcome = PendingEnrichmentOutcome.Updated)))
        advanceUntilIdle()

        assertEquals(1, fake.enrichmentTasks.calls)
        assertEquals(0, vm.uiState.value.enrichment.activeCount)
        assertNull(vm.uiState.value.enrichment.feedback)
        assertEquals(listOf(uploadTestBinding().copy(ledgerId = "owner")), fake.enrichmentTasks.fetchedBindings)
    }

    @Test
    fun sequentialUploadsKeepIndependentObservations() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val first = CompletableDeferred<Result<PendingEnrichmentTask>>()
        val second = CompletableDeferred<Result<PendingEnrichmentTask>>()
        val fake = FakeReviewActions(
            activeLedgerFlow = ledgerFlow,
            activeLedgerIdProvider = { ledgerFlow.value },
        )
        fake.enrichmentTasks.responder = { publicId ->
            if (publicId == "task-1") first.await() else second.await()
        }
        val vm = pendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks)
        advanceUntilIdle()

        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Done, binding = fake.uploadIntents.currentBinding))
        runCurrent()
        runCurrent()
        fake.uploadIntents.publish(
            observedUpload(1, PendingMutationStatus.Done, binding = fake.uploadIntents.currentBinding),
            observedUpload(2, PendingMutationStatus.Done, binding = fake.uploadIntents.currentBinding),
        )
        runCurrent()
        runCurrent()
        assertEquals(2, vm.uiState.value.enrichment.activeCount)

        first.complete(Result.success(task(status = "completed", outcome = PendingEnrichmentOutcome.NoResult)))
        runCurrent()
        assertEquals(1, vm.uiState.value.enrichment.activeCount)

        second.complete(Result.success(task(status = "cancelled")))
        advanceUntilIdle()
        assertEquals(0, vm.uiState.value.enrichment.activeCount)
        assertEquals(PendingEnrichmentFeedbackKind.Cancelled, vm.uiState.value.enrichment.feedback?.kind)
    }

    @Test
    fun delayedPreEnrichmentRefreshCannotReplaceTheTerminalSnapshot() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val delayed = CompletableDeferred<Result<List<com.ticketbox.domain.model.Expense>>>()
        var refreshNumber = 0
        val fake = FakeReviewActions(
            activeLedgerFlow = ledgerFlow,
            activeLedgerIdProvider = { ledgerFlow.value },
        ).apply {
            fetchPendingResponder = {
                refreshNumber += 1
                when (refreshNumber) {
                    1 -> Result.success(emptyList()) // ViewModel init.
                    2 -> delayed.await() // Upload-success refresh, captured before OCR.
                    else -> Result.success(listOf(expense(id = 12L, merchant = "识别后")))
                }
            }
        }
        val vm = pendingViewModel(fake)
        advanceUntilIdle()

        vm.refresh()
        runCurrent()
        vm.refresh()
        runCurrent()
        assertEquals("识别后", vm.uiState.value.items.single().merchant)

        delayed.complete(Result.success(listOf(expense(id = 12L, merchant = "识别前"))))
        advanceUntilIdle()

        assertEquals("识别后", vm.uiState.value.items.single().merchant)
    }

    @Test
    fun reopeningResumesOnlyReceiptsStillInTheAuthoritativePendingList() = review {
        val fake = FakeReviewActions(pending = listOf(expense(1)))
        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Done), observedUpload(2, PendingMutationStatus.Done))
        var changes = 0
        fake.enrichmentTasks.responder = {
            if (fake.enrichmentTasks.calls == 1) Result.success(task("running"))
            else {
                fake.pending = listOf(expense(1, merchant = "restored result"))
                Result.success(task("completed", PendingEnrichmentOutcome.Updated))
            }
        }
        val vm = pendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks, onDataChanged = { changes++ })
        advanceUntilIdle()
        assertEquals(listOf("task-1", "task-1"), fake.enrichmentTasks.fetchedTaskIds)
        assertEquals("restored result", vm.uiState.value.items.single().merchant)
        assertEquals(0, changes) // Historical delivery is not a newly accepted receipt.
        vm.refresh()
        advanceUntilIdle()
        assertEquals(2, fake.enrichmentTasks.calls)
    }

    @Test
    fun historicalNoResultTaskIsProbedOnceWithoutReplayingFeedbackOrRefresh() = review {
        val fake = FakeReviewActions(pending = listOf(expense(1)))
        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Done))
        val vm = pendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks)
        advanceUntilIdle()
        assertEquals(1, fake.enrichmentTasks.calls)
        assertEquals(1, fake.fetchPendingCalls)
        assertNull(vm.uiState.value.enrichment.feedback)
        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Done), observedUpload(2))
        vm.refresh()
        advanceUntilIdle()
        assertEquals(1, fake.enrichmentTasks.calls)
    }

    @Test
    fun aRestoredTaskCommittedAfterTheFirstPendingReadStillInstallsItsResult() = review {
        val fake = FakeReviewActions(pending = listOf(expense(1, merchant = "before enrichment")))
        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Done))
        fake.enrichmentTasks.responder = {
            fake.pending = listOf(expense(1, merchant = "after enrichment"))
            Result.success(task("completed", PendingEnrichmentOutcome.Updated))
        }
        var changes = 0
        val vm = pendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks, onDataChanged = { changes++ })
        advanceUntilIdle()
        assertEquals("after enrichment", vm.uiState.value.items.single().merchant)
        assertEquals(1, fake.enrichmentTasks.calls)
        assertEquals(2, fake.fetchPendingCalls)
        assertNull(vm.uiState.value.enrichment.feedback)
        assertEquals(0, changes)
    }

    private fun task(
        status: String,
        outcome: PendingEnrichmentOutcome? = null,
    ): PendingEnrichmentTask = PendingEnrichmentTask(
        status = status,
        outcome = outcome,
    )
}
