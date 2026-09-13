package com.ticketbox.viewmodel

import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.data.repository.ExpenseCorrectionObservation
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.expenseFactBundleDtoFixture
import com.ticketbox.data.repository.toDomain
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.FamilyMember
import com.ticketbox.domain.model.ProtectedImage
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.TestScope
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactCorrectionBundleTest : ExpenseFactViewModelTestBase() {
    @Test
    fun `bundle root restores the first sent list when root GET fails without duplicate reads`() = edit { fake ->
        val current = expenseFactBundleDtoFixture().toDomain()
        val stale = current.copy(root = current.root.copy(amountCents = null, rowVersion = current.root.rowVersion - 1))
        fake.baseExpense = stale.root
        fake.fetchExpenseFailure = RepositoryException(errorCode = "server_unavailable", message = "offline")
        fake.factBundleResult = { Result.success(current) }
        fake.billSplitSentResult = { Result.success(listOf(
            fake.sentInvite(publicId = "this-fact", senderExpenseId = current.root.id),
            fake.sentInvite(publicId = "other-fact", senderExpenseId = current.root.id + 1),
        )) }
        val vm = ExpenseFactViewModel(expenseId = current.root.id, repository = fake)
        advanceUntilIdle()

        assertEquals(current.root, vm.uiState.value.expense)
        assertEquals(listOf("this-fact"), vm.uiState.value.billSplitSent.map { it.publicId })
        assertEquals(BillSplitSentLoadState.Loaded, vm.uiState.value.billSplitSentLoadState)
        assertEquals(1, fake.fetchBillSplitSentCalls)
        vm.loadExpenseFactBundle()
        advanceUntilIdle()
        fake.factBundleResult = { Result.success(stale) }
        vm.loadExpenseFactBundle()
        advanceUntilIdle()

        assertEquals(current, vm.uiState.value.factBundle)
        assertEquals(current.root, vm.uiState.value.expense)
        assertEquals(1, fake.fetchBillSplitSentCalls, "Repeated or rejected bundles must not restart the initial list read")
        assertFalse(vm.consumeDoneAdviceInputsChanged())
    }

    @Test
    fun `binding initialization restores metadata and ignores old auxiliary replies`() = edit { fake ->
        val first = fake.correctionBinding
        val second = first.copy(ownerKey = "another-owner", sessionGeneration = "next-session", bindingRevision = "next-binding")
        val observations = MutableStateFlow(ExpenseCorrectionObservation(LedgerAccessContext(first, true), emptyList()))
        val oldCategories = CompletableDeferred<Result<List<String>>>()
        val oldMembers = CompletableDeferred<Result<List<FamilyMember>>>()
        val oldSent = CompletableDeferred<Result<List<BillSplitSent>>>()
        val reads = mutableListOf<String>()
        val repository = object : ExpenseFactActions by fake {
            override fun observeCorrections() = observations
            override suspend fun categories(): Result<List<String>> {
                val old = observations.value.access?.binding == first
                reads += "categories:$old"
                return if (old) oldCategories.await() else Result.success(listOf("新家庭自定义"))
            }
            override suspend fun fetchSplitMembers(): Result<List<FamilyMember>> {
                val old = observations.value.access?.binding == first
                reads += "members:$old"
                return if (old) oldMembers.await() else Result.success(listOf(fake.member(3L, displayName = "新家庭成员")))
            }
            override suspend fun fetchBillSplitSent(binding: LogicalSessionBinding): Result<List<BillSplitSent>> {
                val old = observations.value.access?.binding == first
                reads += "sent:$old"
                return if (old) oldSent.await() else Result.success(listOf(fake.sentInvite(publicId = "new-family")))
            }
        }
        val vm = ExpenseFactViewModel(expenseId = fake.baseExpense.id, repository = repository)
        advanceUntilIdle()
        assertEquals(setOf("categories:true", "members:true", "sent:true"), reads.toSet())
        fake.baseExpense = fake.baseExpense.copy(merchant = "新家庭事实")
        observations.value = ExpenseCorrectionObservation(LedgerAccessContext(second, true), emptyList())
        advanceUntilIdle()

        assertEquals(listOf("新家庭自定义"), vm.uiState.value.categories)
        assertEquals(mapOf(3L to "新家庭成员"), vm.uiState.value.revisionMemberNames)
        assertEquals(listOf("new-family"), vm.uiState.value.billSplitSent.map { it.publicId })
        oldCategories.complete(Result.success(listOf("旧家庭自定义")))
        oldMembers.complete(Result.success(listOf(fake.member(3L, displayName = "旧家庭成员"))))
        oldSent.complete(Result.failure(RepositoryException(errorCode = "binding_changed", message = "old binding")))
        advanceUntilIdle()

        assertEquals(second, vm.uiState.value.correctionAccess?.binding)
        assertEquals("新家庭事实", vm.uiState.value.expense?.merchant)
        assertEquals(listOf("新家庭自定义"), vm.uiState.value.categories)
        assertEquals(mapOf(3L to "新家庭成员"), vm.uiState.value.revisionMemberNames)
        assertEquals(listOf("new-family"), vm.uiState.value.billSplitSent.map { it.publicId })
        assertEquals(BillSplitSentLoadState.Loaded, vm.uiState.value.billSplitSentLoadState)
        assertNull(vm.uiState.value.billSplitMessage)
        assertEquals(6, reads.size, "Each binding initializes each auxiliary owner once")
        assertFalse(vm.consumeDoneAdviceInputsChanged())
    }

    @Test
    fun `synced correction retires the old refund summary even when its refresh fails`() = edit { fake ->
        val original = expenseFactBundleDtoFixture().toDomain()
        fake.baseExpense = original.root
        fake.factBundleResult = { Result.success(original) }
        val vm = ExpenseFactViewModel(expenseId = original.root.id, repository = fake)
        advanceUntilIdle()
        assertEquals(900L, vm.uiState.value.factBundle?.financialSummary?.lineageHomeNetCents)

        val corrected = original.root.copy(
            amountCents = 1_400L,
            originalAmountMinor = 1_400L,
            rowVersion = original.root.rowVersion + 1,
            factRevision = original.root.factRevision + 1,
        )
        fake.factBundleResult = {
            assertNull(vm.uiState.value.factBundle, "A committed correction invalidates the old summary before reading")
            Result.failure(RepositoryException(errorCode = "server_unavailable", message = "offline"))
        }
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Amount, "14.00")
        vm.updateCorrectionField(CorrectionScalarField.Reason, "Correct the original bill amount")
        vm.submitCorrection()
        advanceUntilIdle()
        fake.baseExpense = corrected
        fake.settleCorrection(PendingMutationStatus.Done)
        advanceUntilIdle()

        assertEquals(2, fake.fetchFactBundleCalls, "Correction success must refresh the existing fact-bundle owner")
        assertEquals(corrected, vm.uiState.value.expense)
        assertNull(vm.uiState.value.factBundle)
        assertEquals(ExpenseDetailDataLoadState.Failed, vm.uiState.value.factBundleLoadState)
        kotlin.test.assertTrue(vm.uiState.value.corrections.single().delivered)

        val refreshed = original.copy(
            root = corrected,
            financialSummary = original.financialSummary.copy(
                grossOriginalMinor = 1_400L,
                grossHomeAmountCents = 1_400L,
                rootStreamAmountCents = 1_400L,
                remainingRefundableOriginalMinor = 1_100L,
                lineageHomeNetCents = 1_100L,
            ),
        )
        fake.factBundleResult = { Result.success(refreshed) }
        vm.loadExpenseFactBundle()
        advanceUntilIdle()

        assertEquals(refreshed, vm.uiState.value.factBundle)
        assertEquals(ExpenseDetailDataLoadState.Loaded, vm.uiState.value.factBundleLoadState)
        kotlin.test.assertTrue(vm.uiState.value.corrections.single().delivered)
    }

    @Test
    fun `old binding image failures leave the new receipt images unchanged`() = edit { fake ->
        assertOldImageFailuresCannotPublish(this, fake)
    }

    private suspend fun assertOldImageFailuresCannotPublish(scope: TestScope, fake: FakeExpenseFactActions) {
        fake.baseExpense = fake.baseExpense.copy(hasImage = true)
        val first = fake.correctionBinding
        val second = first.copy(ledgerId = "new-ledger", bindingRevision = "new-binding")
        val observations = MutableStateFlow(ExpenseCorrectionObservation(LedgerAccessContext(first, true), emptyList()))
        val oldThumbnail = CompletableDeferred<Result<ProtectedImage>>()
        val oldFullImage = CompletableDeferred<Result<ProtectedImage>>()
        val firstThumbnail = ProtectedImage(byteArrayOf(1), "image/png")
        val currentThumbnail = ProtectedImage(byteArrayOf(2), "image/png")
        val currentFullImage = ProtectedImage(byteArrayOf(3), "image/png")
        var retryOldThumbnail = false
        val startedReads = mutableListOf<String>()
        val repository = object : ExpenseFactActions by fake {
            override fun observeCorrections() = observations
            override suspend fun fetchThumbnail(id: Long): Result<ProtectedImage> {
                if (observations.value.access?.binding == second) return Result.success(currentThumbnail)
                if (!retryOldThumbnail) return Result.success(firstThumbnail)
                startedReads += "old-thumbnail"
                return oldThumbnail.await()
            }
            override suspend fun fetchImage(id: Long): Result<ProtectedImage> {
                if (observations.value.access?.binding == second) return Result.success(currentFullImage)
                startedReads += "old-full-image"
                return oldFullImage.await()
            }
        }
        val vm = ExpenseFactViewModel(expenseId = fake.baseExpense.id, repository = repository)
        scope.advanceUntilIdle()
        assertEquals(firstThumbnail, vm.uiState.value.thumbnail)
        retryOldThumbnail = true
        vm.retryLoadThumbnail()
        vm.loadFullImage()
        scope.advanceUntilIdle()
        assertEquals(listOf("old-thumbnail", "old-full-image"), startedReads)
        assertTrue(vm.uiState.value.imageLoading)

        observations.value = ExpenseCorrectionObservation(LedgerAccessContext(second, true), emptyList())
        scope.advanceUntilIdle()
        vm.loadFullImage()
        scope.advanceUntilIdle()
        assertEquals(second, vm.uiState.value.correctionAccess?.binding)
        assertEquals(currentThumbnail, vm.uiState.value.thumbnail)
        assertEquals(currentFullImage, vm.uiState.value.fullImage)
        assertEquals(ExpenseDetailDataLoadState.Loaded, vm.uiState.value.thumbnailLoadState)
        assertFalse(vm.uiState.value.imageLoading)
        val currentState = vm.uiState.value

        // BoundLedgerRequest rejects an old binding even when its HTTP request finishes.
        val staleFailure = RepositoryException(errorCode = "binding_changed", message = "old binding")
        oldThumbnail.complete(Result.failure(staleFailure))
        oldFullImage.complete(Result.failure(staleFailure))
        scope.advanceUntilIdle()

        assertEquals(currentState, vm.uiState.value, "Neither old failure may replace the new receipt or its status")
    }
}
