package com.ticketbox.viewmodel

import com.ticketbox.domain.model.PendingEnrichmentOutcome
import com.ticketbox.domain.model.PendingEnrichmentTask
import com.ticketbox.domain.model.PendingUploadReceipt
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelEnrichmentTest : PendingViewModelReviewTestBase() {

    @Test
    fun everyTerminalTaskOutcomeHasAnHonestConsumerState() {
        val cases = listOf(
            task("completed", PendingEnrichmentOutcome.Updated) to PendingEnrichmentFeedbackKind.Updated,
            task("completed", PendingEnrichmentOutcome.NoResult) to PendingEnrichmentFeedbackKind.NoResult,
            task("completed", PendingEnrichmentOutcome.Conflict) to PendingEnrichmentFeedbackKind.Conflict,
            task("completed", PendingEnrichmentOutcome.NotPending) to PendingEnrichmentFeedbackKind.NotPending,
            task("completed") to PendingEnrichmentFeedbackKind.Failed,
            task("failed") to PendingEnrichmentFeedbackKind.Failed,
            task("cancelled") to PendingEnrichmentFeedbackKind.Cancelled,
        )

        cases.forEach { (task, expected) ->
            assertEquals(expected, task.toPendingEnrichmentFeedbackKind())
        }
    }

    @Test
    fun completedEnrichmentRefreshesTheInitiatingPendingConsumer() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(
            activeLedgerFlow = ledgerFlow,
            activeLedgerIdProvider = { ledgerFlow.value },
        )
        val receipt = PendingUploadReceipt(expenseId = 7L, enrichmentTaskPublicId = "task-7")
        fake.uploadResponder = { Result.success(receipt) }
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
        val vm = PendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks)
        advanceUntilIdle()

        assertTrue(vm.markUploadPreparing())
        assertTrue(vm.uploadPreparedImage(preparedImage("receipt.jpg")))
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
        fake.uploadResponder = { Result.success(PendingUploadReceipt(8L, "task-8")) }
        var taskFetches = 0
        fake.enrichmentTasks.responder = {
            taskFetches += 1
            if (taskFetches == 1) {
                Result.failure(IllegalStateException("offline"))
            } else {
                Result.success(task(status = "completed", outcome = PendingEnrichmentOutcome.NoResult))
            }
        }
        val vm = PendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks)
        advanceUntilIdle()

        assertTrue(vm.markUploadPreparing())
        assertTrue(vm.uploadPreparedImage(preparedImage("receipt.jpg")))
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
        fake.uploadResponder = { Result.success(PendingUploadReceipt(9L, "task-9")) }
        fake.enrichmentTasks.responder = { taskResponse.await() }
        val vm = PendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks)
        advanceUntilIdle()

        assertTrue(vm.markUploadPreparing())
        assertTrue(vm.uploadPreparedImage(preparedImage("receipt.jpg")))
        runCurrent()
        assertEquals(1, vm.uiState.value.enrichment.activeCount)

        ledgerFlow.value = "family"
        runCurrent()
        taskResponse.complete(Result.success(task(status = "completed", outcome = PendingEnrichmentOutcome.Updated)))
        advanceUntilIdle()

        assertEquals(1, fake.enrichmentTasks.calls)
        assertEquals(0, vm.uiState.value.enrichment.activeCount)
        assertNull(vm.uiState.value.enrichment.feedback)
    }

    @Test
    fun sequentialUploadsKeepIndependentObservations() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val first = CompletableDeferred<Result<PendingEnrichmentTask>>()
        val second = CompletableDeferred<Result<PendingEnrichmentTask>>()
        var uploadNumber = 0
        val fake = FakeReviewActions(
            activeLedgerFlow = ledgerFlow,
            activeLedgerIdProvider = { ledgerFlow.value },
        )
        fake.uploadResponder = {
            uploadNumber += 1
            Result.success(PendingUploadReceipt(uploadNumber.toLong(), "task-$uploadNumber"))
        }
        fake.enrichmentTasks.responder = { publicId ->
            if (publicId == "task-1") first.await() else second.await()
        }
        val vm = PendingViewModel(fake, enrichmentTaskReader = fake.enrichmentTasks)
        advanceUntilIdle()

        assertTrue(vm.markUploadPreparing())
        assertTrue(vm.uploadPreparedImage(preparedImage("first.jpg")))
        runCurrent()
        assertTrue(vm.markUploadPreparing())
        assertTrue(vm.uploadPreparedImage(preparedImage("second.jpg")))
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

    private fun preparedImage(name: String): PreparedUploadImage = PreparedUploadImage(
        fileName = name,
        contentType = "image/jpeg",
        bytes = name.encodeToByteArray(),
        sourceSizeBytes = name.length.toLong(),
    )

    private fun task(
        status: String,
        outcome: PendingEnrichmentOutcome? = null,
    ): PendingEnrichmentTask = PendingEnrichmentTask(
        status = status,
        outcome = outcome,
    )
}
