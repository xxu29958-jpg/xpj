package com.ticketbox.viewmodel

import com.ticketbox.R
import com.ticketbox.domain.model.UiText
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/**
 * W1：系统分享多图直传的 ViewModel 契约。验证 [PendingViewModel.uploadPreparedImage]
 * 顺序逐张走在线-only 上传链、计数/顺序正确、单张失败不阻断其余张、在线-only 失败
 * 会冒泡到 message。纯 JVM（FakeReviewActions），不碰 android.net.Uri。
 */
@OptIn(ExperimentalCoroutinesApi::class)
class PendingViewModelShareUploadTest : PendingViewModelReviewTestBase() {

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
        fake.uploadResponder = { Result.success(it.length.toLong()) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        val results = mutableListOf<Boolean>()
        for (name in listOf("a.jpg", "b.jpg", "c.jpg")) {
            assertTrue(vm.markUploadPreparing())
            results += vm.uploadPreparedImage(preparedImage(name))
            advanceUntilIdle()
        }

        assertEquals(listOf(true, true, true), results)
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
            if (name == "fail.jpg") Result.failure(IllegalStateException("boom")) else Result.success(1L)
        }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.markUploadPreparing())
        val first = vm.uploadPreparedImage(preparedImage("fail.jpg"))
        advanceUntilIdle()
        assertFalse(first)
        // 失败后 uploading 已复位，第二张能重新拿锁。
        assertFalse(vm.uiState.value.uploading)

        assertTrue(vm.markUploadPreparing())
        val second = vm.uploadPreparedImage(preparedImage("ok.jpg"))
        advanceUntilIdle()
        assertTrue(second)

        assertEquals(2, fake.uploadCalls)
        assertEquals(listOf("fail.jpg", "ok.jpg"), fake.uploadedFileNames)
    }

    @Test
    fun onlineOnlyFailureSurfacesUploadFailedMessage() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        // 无 message 的失败 → toUiText 回退到屏级文案（带 message 会走 UiText.raw）。
        fake.uploadResponder = { Result.failure(IllegalStateException()) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.markUploadPreparing())
        val ok = vm.uploadPreparedImage(preparedImage("x.jpg"))
        advanceUntilIdle()

        assertFalse(ok)
        // 上传链是在线-only：失败即提示既有上传失败文案（非排队）。
        assertEquals(UiText.res(R.string.pending_msg_upload_failed), vm.uiState.value.message)
        assertFalse(vm.uiState.value.uploading)
    }

    @Test
    fun ledgerSwitchBetweenImagesDropsTheInFlightOne() = review {
        val ledgerFlow = MutableStateFlow<String?>("owner")
        val fake = FakeReviewActions(activeLedgerFlow = ledgerFlow, activeLedgerIdProvider = { ledgerFlow.value })
        fake.uploadResponder = { Result.success(1L) }
        val vm = PendingViewModel(fake)
        advanceUntilIdle()

        assertTrue(vm.markUploadPreparing())
        // Ledger switches after the lock snapshot — guard must drop this one
        // before the repository call, like the single-image picker path.
        ledgerFlow.value = "family"
        advanceUntilIdle()
        val ok = vm.uploadPreparedImage(preparedImage("y.jpg"))
        advanceUntilIdle()

        assertFalse(ok)
        assertEquals(0, fake.uploadCalls)
        assertEquals(UiText.res(R.string.pending_msg_upload_ledger_switched), vm.uiState.value.message)
    }
}
