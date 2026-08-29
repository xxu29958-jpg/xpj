package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.PendingUploadReceipt
import com.ticketbox.domain.model.UiText
import com.ticketbox.ui.navigation.uploadSharedImageSequence
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

/**
 * W1：系统分享多图直传的 ViewModel 契约。验证 [PendingViewModel.uploadPreparedImage]
 * 顺序逐张走在线-only 上传链、计数/顺序正确、单张失败不阻断其余张、在线-only 失败
 * 会冒泡到 message。纯 JVM（FakeReviewActions），不碰 android.net.Uri。
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingViewModelShareUploadTest : PendingViewModelReviewTestBase() {

    private fun preparedImage(name: String): PreparedUploadImage = PreparedUploadImage(
        fileName = name,
        contentType = "image/jpeg",
        bytes = name.encodeToByteArray(),
        sourceSizeBytes = name.length.toLong(),
    )

    @Test
    fun multipleSharedImagesUploadSequentiallyInOrder() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        fake.uploadResponder = {
            Result.success(PendingUploadReceipt(it.length.toLong(), "task-$it"))
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        uploadSharedImageSequence(vm, listOf("a.jpg", "b.jpg", "c.jpg")) { preparedImage(it) }
        advanceUntilIdle()

        assertEquals(3, fake.uploadCalls)
        assertEquals(listOf("a.jpg", "b.jpg", "c.jpg"), fake.uploadedFileNames)
        // 每张完成后回到非上传态（成功后会触发 refresh，故不在此断言瞬时的成功文案）。
        assertFalse(vm.uiState.value.uploading)
    }

    @Test
    fun secondImageStillUploadsAfterFirstFails() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        // First call fails (online-only error), the rest succeed.
        fake.uploadResponder = { name ->
            if (name == "fail.jpg") {
                Result.failure(IllegalStateException("boom"))
            } else {
                Result.success(PendingUploadReceipt(1L, "task-$name"))
            }
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        uploadSharedImageSequence(vm, listOf("fail.jpg", "ok.jpg")) { preparedImage(it) }
        advanceUntilIdle()

        assertEquals(2, fake.uploadCalls)
        assertEquals(listOf("fail.jpg", "ok.jpg"), fake.uploadedFileNames)
        assertEquals(UiText.res(R.string.pending_msg_share_partial_failure, 1), vm.uiState.value.message)
    }

    @Test
    fun capacityFailureRetainsPreparedBytesForOneTapRetry() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        var attempt = 0
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        fake.uploadResponder = {
            attempt += 1
            if (attempt == 1) {
                Result.failure(
                    RepositoryException(
                        message = "识别队列暂时已满。",
                        errorCode = "enrichment_capacity_full",
                    ),
                )
            } else {
                Result.success(PendingUploadReceipt(8L, "task-retry"))
            }
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        val uploadAttempt = assertNotNull(vm.beginUploadPreparation())
        assertFalse(vm.uploadPreparedImage(preparedImage("retry.jpg"), uploadAttempt))
        advanceUntilIdle()

        assertTrue(vm.uiState.value.canRetryUpload)
        assertEquals(UiText.res(R.string.pending_msg_upload_capacity_full), vm.uiState.value.message)

        vm.retryCapacityUpload()
        advanceUntilIdle()

        assertEquals(listOf("retry.jpg", "retry.jpg"), fake.uploadedFileNames)
        assertFalse(vm.uiState.value.canRetryUpload)
        assertTrue(vm.uiState.value.message == null)
    }

    @Test
    fun multiImageShareStopsBeforeDiscardingCapacityRetainedImage() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        fake.uploadResponder = { name ->
            if (name == "first.jpg") {
                Result.failure(
                    RepositoryException(
                        message = "识别队列暂时已满。",
                        errorCode = "enrichment_capacity_full",
                    ),
                )
            } else {
                Result.success(PendingUploadReceipt(8L, "task-$name"))
            }
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        uploadSharedImageSequence(vm, listOf("first.jpg", "second.jpg")) { preparedImage(it) }
        advanceUntilIdle()

        assertEquals(listOf("first.jpg"), fake.uploadedFileNames)
        assertTrue(vm.uiState.value.canRetryUpload)
        assertEquals(UiText.res(R.string.pending_msg_upload_capacity_full), vm.uiState.value.message)
    }

    @Test
    fun capacityRetryNeverRebindsOldImageToAChangedLedger() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        var currentLedgerId: String? = "owner"
        var attempt = 0
        val fake = FakeReviewActions(
            activeLedgerFlow = ledgerFlow,
            // Model the real propagation window where the binding source has
            // changed but the observer coroutine has not published its event.
            activeLedgerIdProvider = { currentLedgerId },
        )
        fake.uploadResponder = {
            attempt += 1
            if (attempt == 1) {
                Result.failure(
                    RepositoryException(
                        message = "识别队列暂时已满。",
                        errorCode = "enrichment_capacity_full",
                    ),
                )
            } else {
                Result.success(PendingUploadReceipt(8L, "task-wrong-ledger"))
            }
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        val uploadAttempt = assertNotNull(vm.beginUploadPreparation())
        assertFalse(vm.uploadPreparedImage(preparedImage("owner-receipt.jpg"), uploadAttempt))
        assertTrue(vm.uiState.value.canRetryUpload)

        currentLedgerId = "family"
        vm.retryCapacityUpload()
        advanceUntilIdle()

        assertEquals(1, fake.uploadCalls)
        assertFalse(vm.uiState.value.canRetryUpload)
        assertEquals(UiText.res(R.string.pending_msg_upload_ledger_switched), vm.uiState.value.message)
    }

    @Test
    fun stalePreparedImageCannotBorrowANewerLedgerAttempt() = review {
        val ledgerFlow = MutableStateFlow<String?>("ledger-a")
        var activeLedgerId: String? = "ledger-a"
        val fake = FakeReviewActions(
            activeLedgerFlow = ledgerFlow,
            activeLedgerIdProvider = { activeLedgerId },
        )
        fake.uploadResponder = { name ->
            Result.success(PendingUploadReceipt(name.length.toLong(), "task-$name"))
        }
        val vm = PendingViewModel(fake)
        val firstPreparing = CompletableDeferred<Unit>()
        val releaseFirst = CompletableDeferred<Unit>()
        val secondPreparing = CompletableDeferred<Unit>()
        val releaseSecond = CompletableDeferred<Unit>()
        advanceUntilIdle()

        val firstJob = launch {
            uploadSharedImageSequence(vm, listOf("ledger-a.jpg")) {
                firstPreparing.complete(Unit)
                releaseFirst.await()
                preparedImage(it)
            }
        }
        firstPreparing.await()

        activeLedgerId = "ledger-b"
        ledgerFlow.value = activeLedgerId
        advanceUntilIdle()

        val secondJob = launch {
            uploadSharedImageSequence(vm, listOf("ledger-b.jpg")) {
                secondPreparing.complete(Unit)
                releaseSecond.await()
                preparedImage(it)
            }
        }
        secondPreparing.await()

        releaseFirst.complete(Unit)
        firstJob.join()

        assertTrue(fake.uploadedFileNames.isEmpty())

        releaseSecond.complete(Unit)
        secondJob.join()

        assertEquals(listOf("ledger-b.jpg"), fake.uploadedFileNames)
        assertEquals("ledger-b", fake.uploadedLedgerIds.single())
    }
}
