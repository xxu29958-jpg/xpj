package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.PendingUploadReceipt
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.navigation.prepareAndUploadSingleImage
import com.ticketbox.ui.navigation.uploadSharedImageSequence
import com.ticketbox.upload.PreparedUploadImage
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelUploadFailureTest : PendingViewModelReviewTestBase() {
    private fun preparedImage(name: String): PreparedUploadImage = PreparedUploadImage(
        fileName = name,
        contentType = "image/jpeg",
        bytes = name.encodeToByteArray(),
        sourceSizeBytes = name.length.toLong(),
    )

    @Test
    fun onlineOnlyFailureSurfacesUploadFailedMessage() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        fake.uploadResponder = { Result.failure(IllegalStateException()) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        val uploadAttempt = assertNotNull(vm.beginUploadPreparation())
        val ok = vm.uploadPreparedImage(preparedImage("x.jpg"), uploadAttempt)
        advanceUntilIdle()

        assertFalse(ok)
        assertEquals(UiText.res(R.string.pending_msg_upload_failed), vm.uiState.value.message)
        assertFalse(vm.uiState.value.uploading)
    }

    @Test
    fun ledgerSwitchBetweenImagesDropsTheInFlightOne() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        fake.uploadResponder = { Result.success(PendingUploadReceipt(1L, "task-upload")) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        val uploadAttempt = assertNotNull(vm.beginUploadPreparation())
        ledgerFlow.value = "family"
        advanceUntilIdle()
        val ok = vm.uploadPreparedImage(preparedImage("y.jpg"), uploadAttempt)
        advanceUntilIdle()

        assertFalse(ok)
        assertEquals(0, fake.uploadCalls)
        assertEquals(UiText.res(R.string.pending_msg_upload_ledger_switched), vm.uiState.value.message)
    }

    @Test
    fun cancelledSharePreparationReleasesTheUploadOwner() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        val vm = PendingViewModel(fake)
        val preparing = CompletableDeferred<Unit>()
        advanceUntilIdle()

        val shareJob = launch {
            uploadSharedImageSequence(vm, listOf("shared.jpg")) {
                preparing.complete(Unit)
                awaitCancellation()
            }
        }
        preparing.await()
        assertTrue(vm.uiState.value.uploading)

        shareJob.cancelAndJoin()

        assertFalse(vm.uiState.value.uploading)
        assertNotNull(vm.beginUploadPreparation())
    }

    @Test
    fun cancelledPickerPreparationReleasesOnlyItsUploadAttempt() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        val vm = PendingViewModel(fake)
        val uploadAttempt = assertNotNull(vm.beginUploadPreparation())
        val preparing = CompletableDeferred<Unit>()
        advanceUntilIdle()

        val pickerJob = launch {
            prepareAndUploadSingleImage(vm, uploadAttempt) {
                preparing.complete(Unit)
                awaitCancellation()
            }
        }
        preparing.await()
        assertTrue(vm.uiState.value.uploading)

        pickerJob.cancelAndJoin()

        assertFalse(vm.uiState.value.uploading)
        assertNotNull(vm.beginUploadPreparation())
    }

    @Test
    fun pickerPreparationExceptionReleasesTheAttemptAndSurfacesFailure() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        val vm = PendingViewModel(fake)
        val uploadAttempt = assertNotNull(vm.beginUploadPreparation())
        advanceUntilIdle()

        prepareAndUploadSingleImage(vm, uploadAttempt) {
            throw IOException("provider read failed")
        }

        assertFalse(vm.uiState.value.uploading)
        assertEquals(UiText.res(R.string.pending_msg_upload_unreadable), vm.uiState.value.message)
        assertNotNull(vm.beginUploadPreparation())
    }

    @Test
    fun sharedPreparationExceptionContinuesAndReportsTheMissingImage() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        fake.uploadResponder = { name ->
            Result.success(PendingUploadReceipt(name.length.toLong(), "task-$name"))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        uploadSharedImageSequence(vm, listOf("broken.jpg", "ok.jpg")) { name ->
            if (name == "broken.jpg") throw IOException("provider read failed")
            preparedImage(name)
        }
        advanceUntilIdle()

        assertEquals(listOf("ok.jpg"), fake.uploadedFileNames)
        assertFalse(vm.uiState.value.uploading)
        assertEquals(UiText.res(R.string.pending_msg_share_partial_failure, 1), vm.uiState.value.message)
    }

    @Test
    fun capacityRetrySuccessRestoresEarlierSharedFailureCount() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        var uploadAttempt = 0
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        fake.uploadResponder = { name ->
            uploadAttempt += 1
            if (uploadAttempt <= 2) {
                Result.failure(
                    RepositoryException(
                        message = "识别队列暂时已满。",
                        errorCode = "enrichment_capacity_full",
                    ),
                )
            } else {
                Result.success(PendingUploadReceipt(name.length.toLong(), "task-$name"))
            }
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        uploadSharedImageSequence(vm, listOf("broken.jpg", "capacity.jpg")) { name ->
            if (name == "broken.jpg") throw IOException("provider read failed")
            preparedImage(name)
        }
        advanceUntilIdle()

        assertTrue(vm.uiState.value.canRetryUpload)
        assertEquals(UiText.res(R.string.pending_msg_upload_capacity_full), vm.uiState.value.message)

        vm.retryCapacityUpload()
        advanceUntilIdle()

        assertTrue(vm.uiState.value.canRetryUpload)
        assertEquals(UiText.res(R.string.pending_msg_upload_capacity_full), vm.uiState.value.message)

        vm.retryCapacityUpload()
        advanceUntilIdle()

        assertEquals(listOf("capacity.jpg", "capacity.jpg", "capacity.jpg"), fake.uploadedFileNames)
        assertFalse(vm.uiState.value.canRetryUpload)
        assertEquals(UiText.res(R.string.pending_msg_share_partial_failure, 1), vm.uiState.value.message)
    }

    @Test
    fun multiImageShareStopsWhenItsOriginalLedgerChanges() = review {
        val ledgerFlow = MutableStateFlow<String?>("ledger-a")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        fake.uploadResponder = { name ->
            Result.success(PendingUploadReceipt(name.length.toLong(), "task-$name"))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        uploadSharedImageSequence(vm, listOf("first.jpg", "second.jpg")) { name ->
            if (name == "first.jpg") {
                ledgerFlow.value = "ledger-b"
                runCurrent()
            }
            preparedImage(name)
        }
        advanceUntilIdle()

        assertTrue(fake.uploadedFileNames.isEmpty())
        assertEquals(UiText.res(R.string.pending_msg_upload_ledger_switched), vm.uiState.value.message)
    }
}
