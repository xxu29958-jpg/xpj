package com.ticketbox.viewmodel

import com.ticketbox.domain.model.PendingUploadReceipt
import com.ticketbox.upload.PreparedUploadImage
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull

/**
 * 218-B4 review P2-16: the pending screen carries TWO change callbacks — the
 * shared data-changed one (insights refresh) and a narrow advice-inputs one
 * that must fire ONLY when a pending action lands in confirmed expenses (the
 * budget advisor's input set). Screenshot uploads and pending-side lifecycle
 * leave the advisor inputs unchanged and must not fire it.
 */
@OptIn(ExperimentalCoroutinesApi::class)
internal class PendingAdviceInvalidationTest : PendingViewModelReviewTestBase() {
    @Test
    fun screenshotUploadDoesNotFireAdviceInvalidation() = review {
        val fake = FakeReviewActions()
        fake.uploadResponder = { Result.success(PendingUploadReceipt(1L, "task-upload")) }
        var invalidations = 0
        val vm = PendingViewModel(fake).also { it.onAdviceInputsChanged = { invalidations += 1 } }
        advanceUntilIdle()

        val uploadAttempt = assertNotNull(vm.beginUploadPreparation())
        vm.uploadPreparedImage(
            PreparedUploadImage(
                fileName = "a.jpg",
                contentType = "image/jpeg",
                bytes = "a.jpg".encodeToByteArray(),
                sourceSizeBytes = 5L,
            ),
            uploadAttempt,
        )
        advanceUntilIdle()

        assertEquals(1, fake.uploadCalls)
        assertEquals(0, invalidations)
    }

    @Test
    fun confirmFiresAdviceInvalidation() = review {
        val target = expense(id = 1, amountCents = 100L)
        val fake = FakeReviewActions(pending = listOf(target))
        fake.confirmResponder = { Result.success(target.copy(status = "confirmed")) }
        var invalidations = 0
        val vm = PendingViewModel(fake).also { it.onAdviceInputsChanged = { invalidations += 1 } }
        advanceUntilIdle()

        vm.confirm(target)
        advanceUntilIdle()

        assertEquals(1, fake.confirmCalls)
        assertEquals(1, invalidations)
    }
}
