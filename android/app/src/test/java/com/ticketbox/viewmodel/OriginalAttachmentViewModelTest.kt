package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OriginalAttachmentActions
import com.ticketbox.data.repository.OriginalCommandObservation
import com.ticketbox.data.repository.OriginalSubmission
import com.ticketbox.data.remote.dto.OriginalHealthDto
import com.ticketbox.domain.model.ProtectedImage
import java.io.IOException
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import org.junit.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class OriginalAttachmentViewModelTest {
    private fun checkTask(block: suspend TestScope.() -> Unit) = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        try { block() } finally { Dispatchers.resetMain() }
    }

    @Test fun onlyRenderedActualOriginalCanBeReviewedAndFailedAdmissionKeepsExactIntent() = checkTask {
        val owner = OriginalActionsFake()
        val handle = SavedStateHandle()
        val actual = ProtectedImage(byteArrayOf(1), "image/png", "b".repeat(64))
        val vm = OriginalAttachmentViewModel(7, owner, { Result.success(actual) }, handle)
        advanceUntilIdle()
        vm.verifyReviewedImage()
        vm.loadImage()
        advanceUntilIdle()
        assertFalse(vm.state.value.canVerify)
        assertTrue(owner.submissions.isEmpty())
        vm.imageDisplayed(actual)
        assertTrue(vm.state.value.canVerify)
        vm.verifyReviewedImage()
        advanceUntilIdle()
        val first = owner.submissions.single()
        assertEquals(actual.originalSha256, first.payload.sha256)
        assertTrue(vm.state.value.localIntent)
        vm.resumeSelectedSource { error("Fileless verification must not read a source") }
        advanceUntilIdle()
        assertEquals(first, owner.submissions.last())
        assertEquals(first.key, handle.get<String>("original_key"))
    }

    @Test fun bindingChangeCannotReuseRenderedEvidenceOrSubmitSavedInputToAnotherLedger() = checkTask {
        val owner = OriginalActionsFake()
        val image = ProtectedImage(byteArrayOf(1), "image/png", "b".repeat(64))
        val vm = OriginalAttachmentViewModel(7, owner, { Result.success(image) }, SavedStateHandle())
        advanceUntilIdle()
        vm.loadImage()
        advanceUntilIdle()
        vm.imageDisplayed(image)
        vm.verifyReviewedImage()
        advanceUntilIdle()
        owner.binding = owner.binding.copy(ledgerId = "other", bindingRevision = "new")
        owner.observations.value = OriginalCommandObservation(LedgerAccessContext(owner.binding, true), emptyList())
        advanceUntilIdle()
        vm.imageDisplayed(image)
        vm.resumeSelectedSource { error("Wrong binding must not read source") }
        advanceUntilIdle()
        assertNull(vm.state.value.reviewedDigest)
        assertFalse(vm.state.value.localIntentBound)
        assertEquals(1, owner.submissions.size)
        assertTrue(vm.state.value.localIntent)
    }

    @Test fun healthReadFailureDoesNotRemoveExistingOriginalReadCapability() = checkTask {
        val owner = OriginalActionsFake()
        owner.healthFailure = IOException("Health endpoint temporarily unavailable")
        val image = ProtectedImage(byteArrayOf(1), "image/png")
        val vm = OriginalAttachmentViewModel(7, owner, { Result.success(image) }, SavedStateHandle())
        advanceUntilIdle()
        assertTrue(vm.state.value.canReadOriginal)
        assertFalse(vm.state.value.canSubmit)
        vm.loadImage()
        advanceUntilIdle()
        assertEquals(image, vm.state.value.image)
        assertFalse(vm.state.value.canVerify)
    }

    @Test fun pendingOriginalReceiptDoesNotReplaceFormBaselineUntilExplicitReview() = checkTask {
        val owner = FakeExpenseEditActions()
        val vm = ExpenseEditViewModel(7, owner)
        advanceUntilIdle()
        val baseline = requireNotNull(vm.uiState.value.expense)
        val fresh = baseline.copy(rowVersion = 2, updatedAt = "2026-09-20T00:00:00Z", imageHash = "a".repeat(64))
        owner.fetchExpenseResponder = { Result.success(fresh) }
        owner.fetchItemsResponder = { Result.success(owner.items(parentRowVersion = 2)) }
        owner.fetchSplitsResponder = { Result.success(owner.splits(parentRowVersion = 2)) }
        vm.originalCommandAccepted()
        assertEquals(baseline, vm.uiState.value.expense)
        vm.confirm(com.ticketbox.domain.model.ExpenseDraft(1000, merchant = "Draft merchant", category = "other",
            note = null, expenseTime = null, tags = null, valueScore = null, regretScore = null))
        advanceUntilIdle()
        assertEquals(0, owner.saveAndConfirmCalls)
        vm.reviewOriginalBaseline()
        advanceUntilIdle()
        assertEquals(fresh, vm.uiState.value.expense)
        assertEquals(baseline.updatedAt, vm.uiState.value.preservedFormTimestamp)
        assertEquals(0, vm.uiState.value.formRevision)
        assertFalse(vm.uiState.value.originalBaselineRequired)
        owner.fetchExpenseResponder = { Result.success(fresh.copy(rowVersion = 3)) }
        owner.fetchItemsResponder = { Result.success(owner.items(parentRowVersion = 3).copy(itemsTotalAmountCents = 500)) }
        owner.fetchSplitsResponder = { Result.success(owner.splits(parentRowVersion = 3)) }
        vm.originalCommandAccepted()
        vm.reviewOriginalBaseline()
        advanceUntilIdle()
        assertEquals(fresh, vm.uiState.value.expense)
        assertTrue(vm.uiState.value.originalBaselineRequired)
        owner.fetchExpenseResponder = { Result.success(fresh.copy(rowVersion = 3, merchant = "Concurrent edit")) }
        vm.originalCommandAccepted()
        vm.reviewOriginalBaseline()
        advanceUntilIdle()
        assertEquals(fresh, vm.uiState.value.expense)
        assertTrue(vm.uiState.value.originalBaselineRequired)
    }
}

private class OriginalActionsFake : OriginalAttachmentActions {
    var binding = LogicalSessionBinding("https://example.test", "ledger", "owner", "session", "binding")
    val observations = MutableStateFlow(OriginalCommandObservation(LedgerAccessContext(binding, true), emptyList()))
    val submissions = mutableListOf<OriginalSubmission>()
    override fun currentOriginalBinding() = binding
    override fun observeOriginalCommands() = observations
    var healthFailure: Throwable? = null
    override suspend fun fetchOriginalHealth(id: Long): Result<OriginalHealthDto> = healthFailure?.let { Result.failure(it) } ?: Result.success(OriginalHealthDto(id, "expense-$id", 4,
        "unverified", "2026-09-20T00:00:00Z", observedSha256 = "a".repeat(64)))
    override suspend fun submitOriginal(request: OriginalSubmission): Result<Long> {
        submissions += request
        return Result.failure(IOException("Synthetic local admission failure"))
    }
    override suspend fun recoverOriginal(binding: LogicalSessionBinding, rowId: Long, drop: Boolean) = Result.success(Unit)
}
