package com.ticketbox.viewmodel

import com.ticketbox.data.repository.UploadBatchRequest

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.UploadAcceptance
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelUploadFailureTest : PendingViewModelReviewTestBase() {
    @Test
    fun acceptanceFailureDoesNotConsumeTheOriginalLaunchAction() = review {
        val fake = FakeReviewActions()
        fake.uploadIntents.accept = { Result.failure(IllegalStateException()) }
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        assertFalse(vm.acceptUploads(UploadBatchRequest(UPLOAD_TEST_BATCH, listOf("a", "b"), uploadTestBinding(), "Asia/Shanghai") { error("Repo owns preparation") }))
        assertEquals(UiText.res(R.string.pending_msg_upload_failed), vm.uiState.value.message)
        assertFalse(vm.uiState.value.uploading)
        assertTrue(vm.uiState.value.canStartUpload)
    }

    @Test
    fun unsupportedUnreadableAndExpiredOriginalsKeepStopWithoutRetry() = review {
        val cases = listOf(
            observedUpload(1, PendingMutationStatus.Failed, "upload_intent_unsupported").copy(payload = null),
            observedUpload(1, PendingMutationStatus.Failed, "upload_source_unreadable").let { it.copy(payload = it.payload!!.copy(file = null)) },
            observedUpload(1, PendingMutationStatus.Failed, "outbox_row_expired"),
            observedUpload(1, PendingMutationStatus.Failed, "upload_original_unavailable"),
            observedUpload(1, PendingMutationStatus.Failed, "idempotency_key_reused:original request refused"),
            observedUpload(1, PendingMutationStatus.Failed, "unsupported_file_type"),
            observedUpload(1, PendingMutationStatus.Failed, "file_too_large"),
            observedUpload(1, PendingMutationStatus.Failed, "invalid_request"),
        )
        for (row in cases) {
            val fake = FakeReviewActions()
            fake.uploadIntents.publish(row)
            val vm = pendingViewModel(fake)
            advanceUntilIdle()
            assertFalse(vm.uiState.value.canRetryUpload)
            assertTrue(vm.uiState.value.canStopUpload)
            assertTrue(vm.uiState.value.uploadMessage != null)
            if (row.row.lastError?.substringBefore(':') == "idempotency_key_reused") {
                assertEquals(UiText.res(R.string.pending_msg_upload_key_refused), vm.uiState.value.uploadMessage)
            }
            assertEquals(row.payload?.file?.metadata?.fileName, vm.uiState.value.upload.originals.single().fileName)
            vm.retryCapacityUpload()
            advanceUntilIdle()
            assertTrue(fake.uploadIntents.recoveries.isEmpty())
            vm.discardCapacityUpload()
            advanceUntilIdle()
            assertEquals(listOf(Triple(uploadTestBinding(), UPLOAD_TEST_BATCH, true)), fake.uploadIntents.recoveries)
        }
    }

    @Test
    fun pendingUnreadableSlotsAreVisibleBeforeAnyNetworkConstrainedDrain() = review {
        val unreadable = observedUpload(2).let { it.copy(payload = it.payload!!.copy(file = null)) }
        for (group in listOf(listOf(unreadable), listOf(observedUpload(1), unreadable))) {
            val fake = FakeReviewActions()
            fake.uploadIntents.publish(*group.toTypedArray())
            val vm = pendingViewModel(fake)
            advanceUntilIdle()
            assertEquals(UiText.res(R.string.pending_msg_upload_unreadable), vm.uiState.value.uploadMessage)
            assertEquals(1, vm.uiState.value.uploadFailedCount)
            assertFalse(vm.uiState.value.canRetryUpload)
            assertTrue(vm.uiState.value.canStopUpload)
            assertEquals(group, fake.uploadIntents.snapshots.value.uploads)
            assertTrue(fake.uploadIntents.recoveries.isEmpty())
        }
    }

    @Test
    fun acceptanceDoesNotPublishAnUnconditionalSavedBytesMessage() = review {
        val fake = FakeReviewActions()
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        assertTrue(vm.acceptUploads(UploadBatchRequest(UPLOAD_TEST_BATCH, listOf("unreadable"), uploadTestBinding(), "Asia/Shanghai") { null }))
        // Acceptance may arrive before the required Room observation; only that observation describes the originals.
        assertNull(vm.uiState.value.message)
        val unreadable = observedUpload(1).let { it.copy(payload = it.payload!!.copy(file = null)) }
        fake.uploadIntents.publish(unreadable)
        advanceUntilIdle()
        assertEquals(UiText.res(R.string.pending_msg_upload_unreadable), vm.uiState.value.uploadMessage)
        assertNull(vm.uiState.value.message)
        assertTrue(vm.uiState.value.canStopUpload)
    }

    @Test
    fun viewerCanInspectAndStopAnOriginalButCannotAcceptOrRetry() = review {
        val fake = FakeReviewActions(canModifyLedger = false)
        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Failed, "http_503"))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        assertFalse(vm.acceptUploads(UploadBatchRequest(UPLOAD_TEST_BATCH, listOf("new"), uploadTestBinding(), "Asia/Shanghai") { null }))
        vm.retryCapacityUpload()
        advanceUntilIdle()
        assertTrue(fake.uploadIntents.accepted.isEmpty())
        assertTrue(fake.uploadIntents.recoveries.isEmpty())
        assertTrue(vm.uiState.value.canStopUpload)
        vm.discardCapacityUpload()
        advanceUntilIdle()
        assertTrue(fake.uploadIntents.recoveries.single().third)
    }

    @Test
    fun cancelledAcceptancePropagatesAndKeepsObservedOriginalRows() = review {
        val fake = FakeReviewActions()
        val row = observedUpload(1)
        fake.uploadIntents.publish(row)
        fake.uploadIntents.accept = { throw CancellationException() }
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        var cancelled = false
        try {
            vm.acceptUploads(UploadBatchRequest(UPLOAD_TEST_BATCH, listOf("new"), uploadTestBinding(), "Asia/Shanghai") { null })
        } catch (_: CancellationException) { cancelled = true }
        assertTrue(cancelled)
        assertEquals(listOf(row), fake.uploadIntents.snapshots.value.uploads)
        assertTrue(fake.uploadIntents.recoveries.isEmpty())
        assertFalse(vm.uiState.value.uploading)
    }

    @Test
    fun closingTheVmCannotConsumeALateAcceptanceOrDropItsOriginal() = review {
        val fake = FakeReviewActions()
        val original = observedUpload(1)
        fake.uploadIntents.publish(original)
        val result = CompletableDeferred<Result<UploadAcceptance>>()
        fake.uploadIntents.accept = { result.await() }
        val vm = pendingViewModel(fake)
        runCurrent()
        var consumed = true
        val job = launch {
            consumed = vm.acceptUploads(UploadBatchRequest(UPLOAD_TEST_BATCH, listOf("original"), uploadTestBinding(), "Asia/Shanghai") { null })
        }
        runCurrent()
        clearPendingViewModels()
        result.complete(Result.success(UploadAcceptance(UPLOAD_TEST_BATCH, listOf(1))))
        job.join()
        assertFalse(consumed)
        assertEquals(listOf(original), fake.uploadIntents.snapshots.value.uploads)
        assertTrue(fake.uploadIntents.recoveries.isEmpty())
    }
}
