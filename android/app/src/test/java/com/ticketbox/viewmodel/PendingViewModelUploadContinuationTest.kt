package com.ticketbox.viewmodel

import com.ticketbox.data.repository.UploadBatchRequest

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.UploadAcceptance
import com.ticketbox.data.repository.UploadIntentObservation
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
internal class PendingViewModelUploadContinuationTest : PendingViewModelReviewTestBase() {
    @Test
    fun pausedGroupAcceptsAnotherOriginalSelectionWithoutImplicitRetry() = review {
        val fake = FakeReviewActions()
        fake.uploadIntents.publish(observedUpload(2, PendingMutationStatus.Failed, "enrichment_capacity_full"), observedUpload(3))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        val nextId = "00000000-0000-0000-0000-000000000002"
        assertTrue(vm.acceptUploads(UploadBatchRequest(nextId, listOf("d", "e"), uploadTestBinding(), "Asia/Shanghai") { null }))
        assertEquals(listOf("d", "e"), fake.uploadIntents.accepted.single().imageRefs)
        assertTrue(fake.uploadIntents.recoveries.isEmpty())
        assertTrue(vm.uiState.value.canRetryUpload)
    }

    @Test
    fun sameLedgerOriginOrAccountSwitchRejectsLateAcceptanceAndClearsOldProjection() = review {
        for (next in listOf(uploadTestBinding().copy(serverUrl = "https://other.local"), uploadTestBinding().copy(ownerKey = "other-owner"))) {
            val fake = FakeReviewActions()
            val result = CompletableDeferred<Result<UploadAcceptance>>()
            fake.uploadIntents.accept = { result.await() }
            fake.uploadIntents.publish(observedUpload(1, PendingMutationStatus.Failed, "enrichment_capacity_full"))
            val vm = pendingViewModel(fake)
            runCurrent()
            var consumed = true
            val acceptance = launch { consumed = vm.acceptUploads(UploadBatchRequest(UPLOAD_TEST_BATCH, listOf("old"), uploadTestBinding(), "Asia/Shanghai") { null }) }
            runCurrent()
            fake.uploadIntents.snapshots.value = UploadIntentObservation(LedgerAccessContext(next, true), emptyList())
            runCurrent()
            result.complete(Result.success(UploadAcceptance(UPLOAD_TEST_BATCH, listOf(1))))
            acceptance.join()
            assertFalse(consumed)
            assertFalse(vm.uiState.value.canStopUpload)
            assertFalse(vm.uiState.value.uploading)
            vm.retryCapacityUpload()
            runCurrent()
            assertTrue(fake.uploadIntents.recoveries.isEmpty())
        }
    }

    @Test
    fun explicitStopUsesTheOriginalGroupAndClosingTheVmDoesNotDropIt() = review {
        val fake = FakeReviewActions()
        fake.uploadIntents.publish(observedUpload(1))
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.discardCapacityUpload()
        advanceUntilIdle()
        assertEquals(listOf(Triple(uploadTestBinding(), UPLOAD_TEST_BATCH, true)), fake.uploadIntents.recoveries)
        clearPendingViewModels()
        assertEquals(1, fake.uploadIntents.recoveries.size)
        assertEquals(1, fake.uploadIntents.snapshots.value.uploads.size)
    }

    @Test
    fun sameBindingRefreshAndFailedStopKeepOriginalRecoveryAvailable() = review {
        val fake = FakeReviewActions()
        val row = observedUpload(1, PendingMutationStatus.Failed, "http_503")
        fake.uploadIntents.publish(row)
        fake.uploadIntents.recover = { Result.failure(IllegalStateException()) }
        val vm = pendingViewModel(fake)
        advanceUntilIdle()
        vm.refresh()
        vm.discardCapacityUpload()
        advanceUntilIdle()
        assertTrue(vm.uiState.value.canRetryUpload)
        assertTrue(vm.uiState.value.canStopUpload)
        assertEquals(listOf(row), fake.uploadIntents.snapshots.value.uploads)
        assertNull(vm.uiState.value.enrichment.feedback)
    }
}
