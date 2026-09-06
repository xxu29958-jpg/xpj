package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.PendingUploadReceipt
import com.ticketbox.domain.model.UiText
import com.ticketbox.upload.PreparedUploadImage
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancel
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelUploadFailureTest : PendingViewModelReviewTestBase() {
    private fun preparedImage(name: String) = PreparedUploadImage(
        fileName = name, contentType = "image/jpeg", bytes = name.encodeToByteArray(),
        sourceSizeBytes = name.length.toLong(),
    )

    @Test
    fun onlineOnlyFailureSurfacesUploadFailedMessage() = review {
        val fake = FakeReviewActions().apply {
            uploadResponder = { Result.failure(IllegalStateException()) }
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.acceptUploads(listOf("x.jpg")) { preparedImage(it) })
        advanceUntilIdle()

        // Local acceptance is not a server receipt.
        assertEquals(1, fake.uploadCalls)
        assertEquals(UiText.res(R.string.pending_msg_upload_failed), vm.uiState.value.message)
        assertFalse(vm.uiState.value.uploading)
    }

    @Test
    fun ledgerSwitchBeforeTheAcceptedBatchRunsDropsIt() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.acceptUploads(listOf("y.jpg")) { preparedImage(it) })
        ledgerFlow.value = "family"
        advanceUntilIdle()

        assertEquals(0, fake.uploadCalls)
        assertEquals(UiText.res(R.string.pending_msg_upload_ledger_switched), vm.uiState.value.message)
    }

    @Test
    fun endingTheViewModelScopeCancelsPreparationAndReleasesTheAcceptedBatch() = review {
        val fake = FakeReviewActions()
        val vm = PendingViewModel(fake)
        val preparing = CompletableDeferred<Unit>()
        advanceUntilIdle()

        assertTrue(vm.acceptUploads(listOf("shared.jpg", "tail.jpg")) {
            preparing.complete(Unit)
            awaitCancellation()
        })
        preparing.await()
        assertTrue(vm.uiState.value.uploading)

        vm.viewModelScope.cancel()
        runCurrent()

        assertFalse(vm.uiState.value.uploading)
        assertFalse(vm.uiState.value.canRetryUpload)
        assertEquals(0, fake.uploadCalls)
        assertFalse(vm.acceptUploads(listOf("new.jpg")) { preparedImage(it) })
    }

    @Test
    fun roleDemotionDuringPreparationStopsTheImageAndTail() = review {
        val fake = FakeReviewActions()
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.acceptUploads(listOf("selected.jpg", "tail.jpg")) {
            fake.canModifyLedgerFlag = false
            preparedImage(it)
        })
        advanceUntilIdle()

        assertEquals(0, fake.uploadCalls)
        assertFalse(vm.uiState.value.uploading)
        assertFalse(vm.uiState.value.canRetryUpload)
        assertEquals(readOnlyMessage(), vm.uiState.value.message)
    }

    @Test
    fun pickerPreparationExceptionReleasesTheBatchAndSurfacesFailure() = review {
        val fake = FakeReviewActions()
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.acceptUploads(listOf("picked.jpg")) { throw IOException("provider read failed") })
        advanceUntilIdle()

        assertFalse(vm.uiState.value.uploading)
        assertEquals(UiText.res(R.string.pending_msg_upload_unreadable), vm.uiState.value.message)
        assertTrue(vm.uiState.value.canStartUpload)
    }

    @Test
    fun sharedPreparationExceptionContinuesAndReportsTheMissingImage() = review {
        val fake = FakeReviewActions().apply {
            uploadResponder = { Result.success(PendingUploadReceipt(1L, "task-upload")) }
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.acceptUploads(listOf("broken.jpg", "ok.jpg")) { name ->
            if (name == "broken.jpg") throw IOException("provider read failed")
            preparedImage(name)
        })
        advanceUntilIdle()

        assertEquals(listOf("ok.jpg"), fake.uploadedFileNames)
        assertFalse(vm.uiState.value.uploading)
        assertEquals(UiText.res(R.string.pending_msg_share_partial_failure, 1), vm.uiState.value.message)
    }

    @Test
    fun repeatedCapacityRetryKeepsEarlierAndUnreadableTailFailuresThenContinues() = review {
        var attempts = 0
        val fake = FakeReviewActions().apply {
            uploadResponder = { name ->
                attempts += 1
                if (attempts <= 2) {
                    Result.failure(RepositoryException("服务正忙", errorCode = "enrichment_capacity_full"))
                } else {
                    Result.success(PendingUploadReceipt(name.length.toLong(), "task-$name"))
                }
            }
        }
        val vm = PendingViewModel(fake)
        val prepared = mutableListOf<String>()
        advanceUntilIdle()

        assertTrue(vm.acceptUploads(listOf("broken.jpg", "capacity.jpg", "broken-tail.jpg", "ok.jpg")) { name ->
            prepared += name
            if (name.startsWith("broken")) throw IOException("provider read failed")
            preparedImage(name)
        })
        advanceUntilIdle()
        assertTrue(vm.uiState.value.canRetryUpload)

        vm.retryCapacityUpload()
        vm.retryCapacityUpload() // A second tap must not create a parallel uploader.
        advanceUntilIdle()
        assertEquals(listOf("capacity.jpg", "capacity.jpg"), fake.uploadedFileNames)
        assertTrue(vm.uiState.value.canRetryUpload)
        assertEquals(UiText.res(R.string.pending_msg_upload_capacity_full), vm.uiState.value.message)

        vm.retryCapacityUpload()
        advanceUntilIdle()

        assertEquals(listOf("capacity.jpg", "capacity.jpg", "capacity.jpg", "ok.jpg"), fake.uploadedFileNames)
        assertEquals(listOf("broken.jpg", "capacity.jpg", "broken-tail.jpg", "ok.jpg"), prepared)
        assertFalse(vm.uiState.value.canRetryUpload)
        assertEquals(UiText.res(R.string.pending_msg_share_partial_failure, 2), vm.uiState.value.message)
    }

    @Test
    fun multiImageShareStopsWhenItsOriginalLedgerChanges() = review {
        val ledgerFlow = MutableStateFlow<String?>("ledger-a")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.acceptUploads(listOf("first.jpg", "second.jpg")) { name ->
            ledgerFlow.value = "ledger-b"
            runCurrent()
            preparedImage(name)
        })
        advanceUntilIdle()

        assertTrue(fake.uploadedFileNames.isEmpty())
        assertEquals(UiText.res(R.string.pending_msg_upload_ledger_switched), vm.uiState.value.message)
    }
}
