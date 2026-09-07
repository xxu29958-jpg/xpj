package com.ticketbox.viewmodel

import com.ticketbox.data.repository.UploadBatchRequest

import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.UploadAcceptance
import com.ticketbox.data.repository.UploadIntentActions
import com.ticketbox.domain.model.UiText
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.launch
import kotlinx.coroutines.flow.flow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.runCurrent
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** VM projections only. File/key/HTTP order is covered by real Repository/Room/engine producers. */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelShareUploadTest : PendingViewModelReviewTestBase() {
    @Test
    fun wholeOriginalSelectionIsAcceptedBeforeTheRouteMayConsumeIt() = review {
        val fake = FakeReviewActions()
        val accepted = CompletableDeferred<Result<UploadAcceptance>>()
        fake.uploadIntents.accept = { accepted.await() }
        var dataChanges = 0
        val vm = pendingViewModel(fake, onDataChanged = { dataChanges++ })
        runCurrent()
        var consumed = false
        val prepare: suspend (String) -> PreparedUploadImage? = { error("VM must not prepare individual slots") }
        val job = launch { consumed = vm.acceptUploads(UploadBatchRequest(UPLOAD_TEST_BATCH, listOf("a", "b", "c"), uploadTestBinding(), "Asia/Shanghai", prepare)) }
        runCurrent()
        assertFalse(consumed)
        assertTrue(vm.uiState.value.uploading)
        val request = fake.uploadIntents.accepted.single()
        assertEquals(listOf("a", "b", "c"), request.imageRefs)
        assertEquals(UPLOAD_TEST_BATCH, request.id)
        assertEquals(uploadTestBinding(), request.expectedBinding)
        assertEquals(prepare, request.prepare)
        accepted.complete(Result.success(UploadAcceptance(UPLOAD_TEST_BATCH, listOf(1, 2, 3))))
        job.join()
        assertTrue(consumed)
        assertEquals(0, dataChanges) // Local acceptance is not a server receipt.
    }

    @Test
    fun reopenedCapacityGroupSurvivesFailedListReadAndRetriesOnlyTheOriginalGroup() = review {
        val fake = FakeReviewActions().apply { fetchPendingResponder = { Result.failure(IllegalStateException()) } }
        val original = listOf(observedUpload(1, PendingMutationStatus.Done),
            observedUpload(2, PendingMutationStatus.Failed, "enrichment_capacity_full"), observedUpload(3))
        fake.uploadIntents.publish(*original.toTypedArray())
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        assertEquals(PendingListLoadState.Failed, vm.uiState.value.listLoadState)
        assertTrue(vm.uiState.value.canRetryUpload)
        assertTrue(vm.uiState.value.canStopUpload)
        assertEquals(
            listOf(PendingUploadOriginalUi(2, "2.jpg"), PendingUploadOriginalUi(3, "3.jpg")),
            vm.uiState.value.upload.originals,
        )
        assertEquals(UiText.res(R.string.pending_msg_upload_capacity_full), vm.uiState.value.uploadMessage)
        vm.retryCapacityUpload()
        advanceUntilIdle()
        assertEquals(listOf(Triple(uploadTestBinding(), UPLOAD_TEST_BATCH, false)), fake.uploadIntents.recoveries)
        assertEquals(original, fake.uploadIntents.snapshots.value.uploads)
        assertTrue(fake.uploadIntents.accepted.isEmpty())
    }

    @Test
    fun ordinaryFailureDoesNotHideTheRunnableTailOrBlockAnotherSelection() = review {
        val fake = FakeReviewActions()
        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Failed, "http_503"), observedUpload(2))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        assertTrue(vm.uiState.value.canRetryUpload)
        assertTrue(vm.uiState.value.canStartUpload)
        assertEquals(1, vm.uiState.value.uploadFailedCount)
        assertEquals(UiText.res(R.string.pending_msg_share_partial_failure, 1), vm.uiState.value.uploadMessage)
        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Failed, "http_503"), observedUpload(2, PendingMutationStatus.Done))
        advanceUntilIdle()
        assertEquals(1, vm.uiState.value.uploadFailedCount)
        assertTrue(vm.uiState.value.canStopUpload)
    }

    @Test
    fun aNewReceiptRefreshesOnceAndAnUnrelatedEmissionDoesNotReplayCompletion() = review {
        val fake = FakeReviewActions()
        var changes = 0
        val vm = pendingViewModel(fake, onDataChanged = { changes++ })
        advanceUntilIdle()
        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Done))
        advanceUntilIdle()
        val refreshes = fake.fetchPendingCalls
        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Done), observedUpload(2))
        advanceUntilIdle()
        assertEquals(1, changes)
        assertEquals(refreshes, fake.fetchPendingCalls)
    }

    @Test
    fun firstAuthoritativeReadWaitsForTheRequiredRoomSnapshot() = review {
        val fake = FakeReviewActions(pending = listOf(expense(1, merchant = "current")))
        fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Done))
        val ready = CompletableDeferred<Unit>()
        val uploads = object : UploadIntentActions by fake.uploadIntents {
            override fun observeUploadIntents() = flow {
                ready.await()
                emit(fake.uploadIntents.snapshots.value)
            }
        }
        var changes = 0
        val vm = pendingViewModel(fake, uploads, onDataChanged = { changes++ })
        runCurrent()
        assertEquals(0, fake.fetchPendingCalls)
        ready.complete(Unit)
        advanceUntilIdle()
        assertEquals(1, fake.fetchPendingCalls)
        assertEquals("current", vm.uiState.value.items.single().merchant)
        assertEquals(uploadTestBinding(), vm.uiState.value.uploadBinding)
        assertEquals(0, changes)
    }
}
