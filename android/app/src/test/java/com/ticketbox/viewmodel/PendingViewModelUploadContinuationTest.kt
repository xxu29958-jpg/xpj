package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.PendingUploadReceipt
import com.ticketbox.domain.model.UiText
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertSame
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelUploadContinuationTest : PendingViewModelReviewTestBase() {
    @Test
    fun aShareAcceptedWhilePausedAppendsAfterTheOriginalTailWithoutRetrying() = review {
        val fake = FakeReviewActions()
        var refused = false
        fake.uploadResponder = { name ->
            if (name == "b" && !refused) {
                refused = true
                Result.failure(RepositoryException("服务正忙", errorCode = "enrichment_capacity_full"))
            } else {
                Result.success(PendingUploadReceipt(name.first().code.toLong(), "task-$name"))
            }
        }
        val vm = PendingViewModel(fake)
        val prepared = mutableListOf<String>()
        advanceUntilIdle()
        assertTrue(vm.acceptUploads(listOf("a", "b", "c")) { prepared += it; preparedImage(it) })
        advanceUntilIdle()
        assertTrue(vm.uiState.value.canRetryUpload)
        assertFalse(vm.uiState.value.canStartUpload)

        assertTrue(vm.acceptUploads(listOf("d", "e")) { prepared += "new:$it"; preparedImage(it) })
        advanceUntilIdle()
        assertEquals(listOf("a", "b"), fake.uploadedFileNames)
        assertEquals(listOf("a", "b"), prepared)
        assertTrue(vm.uiState.value.canRetryUpload)

        vm.retryCapacityUpload()
        advanceUntilIdle()

        assertEquals(listOf("a", "b", "b", "c", "d", "e"), fake.uploadedFileNames)
        assertEquals(listOf("a", "b", "c", "new:d", "new:e"), prepared)
        assertSame(fake.uploadedBytes[1], fake.uploadedBytes[2])
        assertEquals(1, fake.uploadedBindings.distinct().size)
        assertTrue(vm.uiState.value.canStartUpload)
    }

    @Test
    fun sameLedgerNewOriginOrAccountCannotReceiveThePausedIntentOrItsAppend() = review {
        for (changeOrigin in listOf(true, false)) {
            val fake = FakeReviewActions().apply {
                uploadResponder = {
                    Result.failure(RepositoryException("服务正忙", errorCode = "enrichment_capacity_full"))
                }
            }
            val vm = PendingViewModel(fake)
            advanceUntilIdle()
            assertTrue(vm.acceptUploads(listOf("b", "c")) { preparedImage(it) })
            advanceUntilIdle()
            val original = fake.currentUploadBinding()
            fake.uploadBinding = if (changeOrigin) {
                original.copy(serverUrl = "https://other.test")
            } else {
                original.copy(ownerKey = "other-account")
            }

            assertFalse(vm.acceptUploads(listOf("d")) { preparedImage(it) })
            vm.retryCapacityUpload()
            advanceUntilIdle()

            assertEquals(listOf("b"), fake.uploadedFileNames)
            assertFalse(vm.uiState.value.canRetryUpload)
            assertEquals(UiText.res(R.string.pending_msg_upload_ledger_switched), vm.uiState.value.message)
        }
    }

    @Test
    fun changingTheSessionDuringUriPreparationCannotBorrowTheNewBinding() = review {
        val fake = FakeReviewActions()
        val vm = PendingViewModel(fake)
        val preparing = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        advanceUntilIdle()
        assertTrue(vm.acceptUploads(listOf("old", "tail")) {
            preparing.complete(Unit)
            release.await()
            preparedImage(it)
        })
        preparing.await()
        fake.uploadBinding = fake.currentUploadBinding().copy(sessionGeneration = "new-login")
        release.complete(Unit)
        advanceUntilIdle()

        assertEquals(0, fake.uploadCalls)
        assertFalse(vm.uiState.value.uploading)
        assertEquals(UiText.res(R.string.pending_msg_upload_ledger_switched), vm.uiState.value.message)
    }

    @Test
    fun explicitStopReleasesOnlyUnsentImagesAndPermitsANewSelection() = review {
        val fake = FakeReviewActions().apply {
            uploadResponder = {
                Result.failure(RepositoryException("服务正忙", errorCode = "enrichment_capacity_full"))
            }
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()
        assertTrue(vm.acceptUploads(listOf("b", "c")) { preparedImage(it) })
        advanceUntilIdle()

        vm.discardCapacityUpload()
        vm.retryCapacityUpload()
        advanceUntilIdle()
        assertTrue(vm.uiState.value.canStartUpload)
        assertEquals(UiText.res(R.string.pending_msg_upload_stopped), vm.uiState.value.message)

        fake.uploadResponder = { Result.success(PendingUploadReceipt(4L, "task-new")) }
        assertTrue(vm.acceptUploads(listOf("new")) { preparedImage(it) })
        advanceUntilIdle()
        assertEquals(listOf("b", "new"), fake.uploadedFileNames)
    }

    private fun preparedImage(name: String) = PreparedUploadImage(
        fileName = name, contentType = "image/jpeg", bytes = name.encodeToByteArray(),
        sourceSizeBytes = name.length.toLong(),
    )
}
