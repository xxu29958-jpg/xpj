package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseCorrectionDraft
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancel
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.job
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactViewModelRefreshRecoveryTest : ExpenseFactViewModelTestBase() {
    @Test
    fun aLocalConfirmationReceiptBlocksOnlyItsOwnAcceptedFact() = edit { fake ->
        val binding = fake.correctionBinding
        val accepted = OutboxRow(801, binding.serverUrl, binding.ledgerId, binding.ownerKey,
            PendingMutationType.ConfirmExpense, "expense:local:original-create", "{\"expected_row_version\":0}", 0,
            PendingMutationStatus.Done, 0, "correction_refresh_required:1", "2026-09-13T00:00:00Z",
            null, "2026-09-13T00:00:01Z", "original-confirm-key", receiptJson = """{"expenseId":7}""")
        val unrelated = listOf(accepted.copy(id = 802, receiptJson = """{"expenseId":99}"""),
            accepted.copy(id = 803, targetId = "expense:99"))
        fake.expenseOutboxStatus.value = fake.expenseOutboxStatus.value.copy(refreshRequired = unrelated)
        val vm = viewModel(fake)
        try {
            assertTrue(vm.uiState.value.authoritativeRootReady)
            fake.expenseOutboxStatus.value = fake.expenseOutboxStatus.value.copy(refreshRequired = unrelated + accepted)
            advanceUntilIdle()
            assertFalse(vm.uiState.value.authoritativeRootReady, "The original local target resolves through its own accepted receipt")
            assertEquals(2, fake.fetchExpenseCalls)
            assertEquals(accepted, vm.uiState.value.expenseRefreshRequirements.single())
            fake.expenseOutboxStatus.value = fake.expenseOutboxStatus.value.copy(refreshRequired = unrelated)
            advanceUntilIdle()
            assertTrue(vm.uiState.value.authoritativeRootReady)
            assertEquals(2, fake.fetchExpenseCalls)
            assertEquals(0, fake.correctCalls)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun anOffsetReceiptBlocksCachedAndLiveFactsUntilAdoptionWithoutReplacingTheDraft() = edit { fake ->
        fake.baseExpense = fake.baseExpense.copy(rowVersion = 7)
        val vm = viewModel(fake)
        vm.openCorrectionSheet()
        vm.updateCorrectionField(CorrectionScalarField.Merchant, "  My unfinished merchant  ")
        val draft = vm.uiState.value.correction
        val baseline = vm.correctionBaseline
        val binding = fake.correctionBinding
        val original = OutboxRow(901, binding.serverUrl, binding.ledgerId, binding.ownerKey,
            PendingMutationType.CreateExpenseOffset, "expense:${fake.baseExpense.id}", "original-offset-payload", 7,
            PendingMutationStatus.Done, 0, "correction_refresh_required:8", "2026-09-13T00:00:00Z",
            "2026-09-13T00:00:01Z", "2026-09-13T00:00:02Z", "original-offset-key")
        val unrelated = listOf(original.copy(id = 902, ledgerId = "another-ledger"),
            original.copy(id = 903, serverUrl = "https://another.example.test"),
            original.copy(id = 904, ownerKey = binding.ownerKey.replace(
                "00000000-0000-0000-0000-000000000003", "00000000-0000-0000-0000-000000000005")),
            original.copy(id = 905, targetId = "expense:99"))
        fake.expenseOutboxStatus.value = fake.expenseOutboxStatus.value.copy(refreshRequired = unrelated)
        advanceUntilIdle()
        assertTrue(vm.uiState.value.authoritativeRootReady)
        assertEquals(1, fake.fetchExpenseCalls, "Other facts and identities do not invalidate this read")

        fake.baseExpense = fake.baseExpense.copy(rowVersion = 8, merchant = "Accepted current merchant")
        fake.expenseOutboxStatus.value = fake.expenseOutboxStatus.value.copy(refreshRequired = unrelated + original)
        advanceUntilIdle()
        assertEquals(fake.baseExpense, vm.uiState.value.expense)
        assertFalse(vm.uiState.value.authoritativeRootReady, "Root GET alone cannot acknowledge a missing offset stream")
        assertEquals(draft, vm.uiState.value.correction)
        assertEquals(baseline, vm.correctionBaseline)
        assertEquals(2, fake.fetchExpenseCalls)

        val reopened = ExpenseFactViewModel(fake.baseExpense.id, fake, preferLocalCache = true)
        try {
            advanceUntilIdle()
            assertEquals(fake.baseExpense, reopened.uiState.value.expense)
            assertFalse(reopened.uiState.value.authoritativeRootReady, "A matching cached RV still needs full adoption")
            assertEquals(3, fake.fetchExpenseCalls)
            fake.expenseOutboxStatus.value = fake.expenseOutboxStatus.value.copy(queueDepth = 1)
            advanceUntilIdle()
            assertEquals(3, fake.fetchExpenseCalls, "An unchanged receipt must not create a read loop")
            fake.expenseOutboxStatus.value = fake.expenseOutboxStatus.value.copy(refreshRequired = unrelated)
            advanceUntilIdle()
            assertTrue(vm.uiState.value.authoritativeRootReady)
            assertTrue(reopened.uiState.value.authoritativeRootReady)
            assertEquals(draft, vm.uiState.value.correction)
            assertEquals(baseline, vm.correctionBaseline, "An open draft keeps its original OCC")
            assertEquals(3, fake.fetchExpenseCalls, "Acknowledgment does not repeat the completed read")
            assertEquals(0, fake.correctCalls)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
            reopened.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun liveDeliveryAdoptsTheCachedResponseWhenSubsequentReadsAreOffline() = edit { fake ->
        var cached = fake.baseExpense
        val repository = object : ExpenseFactActions by fake {
            override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> = Result.success(cached)
        }
        val vm = ExpenseFactViewModel(fake.baseExpense.id, repository)
        try {
            advanceUntilIdle()
            fake.submitCorrection(fake.correctionBinding, fake.baseExpense,
                ExpenseCorrectionDraft("Correct the receipt", merchant = "Authoritative merchant")).getOrThrow()
            advanceUntilIdle()
            val original = vm.uiState.value.corrections.single().row
            val fresh = fake.baseExpense.copy(rowVersion = 2, factRevision = 2, merchant = "Authoritative merchant")
            cached = fresh
            fake.fetchExpenseFailure = RepositoryException("Connection lost after the accepted response")
            fake.settleCorrection(PendingMutationStatus.Done)
            advanceUntilIdle()

            assertEquals(original.copy(status = PendingMutationStatus.Done), vm.uiState.value.corrections.single().row)
            assertFalse(vm.uiState.value.corrections.single().refreshRequired)
            assertEquals(fresh, vm.uiState.value.expense)
            assertTrue(vm.uiState.value.authoritativeRootReady)
            assertFalse(vm.uiState.value.expenseStale)
            assertEquals(1, fake.fetchExpenseCalls, "The accepted cache does not require another root GET")
            assertEquals(ExpenseDetailDataLoadState.Failed, vm.uiState.value.factBundleLoadState)
            vm.openCorrectionSheet()
            assertTrue(vm.uiState.value.correction.open)
            assertEquals(1, fake.correctCalls)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun unchangedOrMissingCompletionCacheCannotReleaseTheOldRoot() = edit {
        for (cacheMissing in listOf(false, true)) {
            val fake = FakeExpenseFactActions()
            val repository = object : ExpenseFactActions by fake {
                override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> =
                    if (cacheMissing) Result.failure(RepositoryException("Cache retired")) else Result.success(fake.baseExpense)
            }
            val vm = ExpenseFactViewModel(fake.baseExpense.id, repository)
            try {
                advanceUntilIdle()
                fake.submitCorrection(fake.correctionBinding, fake.baseExpense,
                    ExpenseCorrectionDraft("Correct the receipt", merchant = "Authoritative merchant")).getOrThrow()
                advanceUntilIdle()
                val original = vm.uiState.value.corrections.single().row
                fake.fetchExpenseFailure = RepositoryException("Offline")
                fake.settleCorrection(PendingMutationStatus.Done)
                advanceUntilIdle()

                assertEquals(fake.baseExpense, vm.uiState.value.expense)
                assertFalse(vm.uiState.value.authoritativeRootReady)
                assertEquals(ExpenseDetailDataLoadState.Failed, vm.uiState.value.expenseLoadState)
                assertEquals(original.copy(status = PendingMutationStatus.Done), vm.uiState.value.corrections.single().row)
                assertEquals(1, fake.correctCalls)
            } finally {
                vm.viewModelScope.coroutineContext.job.cancelAndJoin()
            }
        }
    }

    @Test
    fun aBindingChangeRejectsTheLateCacheOfANewlyDeliveredCorrection() = edit { fake ->
        fake.observeCorrections()
        val originalRoot = fake.baseExpense
        val started = CompletableDeferred<Unit>()
        val cache = CompletableDeferred<Result<Expense>>()
        val repository = object : ExpenseFactActions by fake {
            override fun observeCorrections() = fake.correctionObservations
            override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> {
                started.complete(Unit)
                return cache.await()
            }
        }
        val vm = ExpenseFactViewModel(originalRoot.id, repository)
        try {
            advanceUntilIdle()
            fake.submitCorrection(fake.correctionBinding, originalRoot,
                ExpenseCorrectionDraft("Original correction", merchant = "Corrected merchant")).getOrThrow()
            advanceUntilIdle()
            fake.settleCorrection(PendingMutationStatus.Done)
            advanceUntilIdle()
            assertTrue(started.isCompleted)
            assertFalse(vm.uiState.value.authoritativeRootReady)

            val binding = fake.correctionBinding.copy(ledgerId = "another-ledger", bindingRevision = "new-binding")
            fake.baseExpense = originalRoot.copy(merchant = "Current ledger root")
            fake.correctionObservations.value = fake.correctionObservations.value.copy(
                access = LedgerAccessContext(binding, true), corrections = emptyList())
            advanceUntilIdle()
            assertTrue(vm.uiState.value.authoritativeRootReady)
            val current = vm.uiState.value
            cache.complete(Result.success(originalRoot.copy(rowVersion = 2, merchant = "Corrected merchant")))
            advanceUntilIdle()

            assertEquals(current, vm.uiState.value)
            assertEquals(binding, vm.uiState.value.correctionAccess?.binding)
            assertEquals(1, fake.correctCalls)
        } finally {
            cache.complete(Result.success(originalRoot))
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }

    @Test
    fun aSuccessfulRootReadKeepsItsResultWhenItAcknowledgesItsOwnReceipt() = edit {
        for (acknowledgeWhileReading in listOf(true, false)) {
            val fake = FakeExpenseFactActions()
            fake.baseExpense = fake.baseExpense.copy(rowVersion = 7)
            fake.seedRefreshRequirement(11)
            val original = fake.correctionObservations.value.corrections.single().row
            val fresh = fake.baseExpense.copy(rowVersion = 11)
            val response = CompletableDeferred<Result<Expense>>()
            var rootReads = 0
            val repository = object : ExpenseFactActions by fake {
                override suspend fun fetchExpense(id: Long): Result<Expense> {
                    rootReads++
                    if (rootReads > 1) return Result.failure(RepositoryException("Connection lost after the first read"))
                    if (acknowledgeWhileReading) fake.clearRefreshRequirement()
                    return response.await()
                }
            }
            val vm = ExpenseFactViewModel(fresh.id, repository, preferLocalCache = true)
            try {
                advanceUntilIdle()
                response.complete(Result.success(fresh))
                advanceUntilIdle()
                if (!acknowledgeWhileReading) fake.clearRefreshRequirement()
                advanceUntilIdle()

                assertEquals(1, rootReads, "Receipt acknowledgment must not issue another root GET")
                assertEquals(fresh, vm.uiState.value.expense)
                assertFalse(vm.uiState.value.expenseStale)
                assertTrue(vm.uiState.value.authoritativeRootReady)
                vm.openCorrectionSheet()
                assertTrue(vm.uiState.value.correction.open)
                assertEquals(original.copy(lastError = null), fake.correctionObservations.value.corrections.single().row)
                assertEquals(1, fake.correctCalls)
                assertFalse(vm.consumeDoneAdviceInputsChanged())
            } finally {
                response.complete(Result.success(fresh))
                vm.viewModelScope.cancel()
            }
        }
    }

    @Test
    fun anotherConsumersAcknowledgmentCannotReleaseThisViewsOlderRoot() = edit { fake ->
        fake.baseExpense = fake.baseExpense.copy(rowVersion = 7)
        fake.seedRefreshRequirement(11)
        fake.fetchExpenseFailure = RepositoryException("Offline")
        var cachedRoot = fake.baseExpense
        val repository = object : ExpenseFactActions by fake {
            override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> = Result.success(cachedRoot)
        }
        val vm = ExpenseFactViewModel(fake.baseExpense.id, repository, preferLocalCache = true)
        advanceUntilIdle()
        assertFalse(vm.uiState.value.authoritativeRootReady)

        fake.fetchExpenseFailure = null
        cachedRoot = fake.baseExpense.copy(rowVersion = 11)
        fake.baseExpense = fake.baseExpense.copy(rowVersion = 8)
        fake.clearRefreshRequirement()
        advanceUntilIdle()
        assertEquals(11L, repository.fetchExpenseFromLocalCache(fake.baseExpense.id).getOrThrow().rowVersion)
        assertEquals(8L, vm.uiState.value.expense?.rowVersion, "The current view received only the older read")
        assertFalse(vm.uiState.value.authoritativeRootReady, "Another cache consumer did not adopt this view's root")
        vm.openCorrectionSheet()
        vm.createRepaymentDraftFromExpense()
        vm.openBillSplitInviteSheet()
        advanceUntilIdle()
        assertFalse(vm.uiState.value.correction.open)
        assertFalse(vm.uiState.value.billSplitInviteSheetOpen)
        assertEquals(0, fake.repaymentDraftCalls)
        assertEquals(0, fake.createBillSplitCalls)

        fake.baseExpense = fake.baseExpense.copy(rowVersion = 11)
        vm.retryLoadExpense()
        advanceUntilIdle()
        assertTrue(vm.uiState.value.authoritativeRootReady)
        vm.openCorrectionSheet()
        assertTrue(vm.uiState.value.correction.open)
        assertEquals(1, fake.correctCalls, "Reading the receipt barrier never replays the original")
        assertFalse(vm.consumeDoneAdviceInputsChanged(), "A historical receipt is not another edit")
    }

    @Test
    fun firstObservationAfterAcknowledgmentAdoptsTheNewerRoomRootWhileOffline() = edit { fake ->
        val initial = fake.baseExpense.copy(rowVersion = 7)
        fake.baseExpense = initial
        fake.seedRefreshRequirement(11)
        fake.clearRefreshRequirement()
        fake.baseExpense = initial.copy(rowVersion = 11, merchant = "Already adopted in Room")
        fake.fetchExpenseFailure = RepositoryException("Offline")
        val vm = ExpenseFactViewModel(initial.id, fake, preferLocalCache = true)
        assertFalse(vm.uiState.value.authoritativeRootReady)
        advanceUntilIdle()

        assertEquals(fake.baseExpense, vm.uiState.value.expense)
        assertTrue(vm.uiState.value.authoritativeRootReady)
        assertEquals(0, fake.fetchExpenseCalls, "A valid bound cache must not require a network root read")
        assertFalse(vm.consumeDoneAdviceInputsChanged())
        assertEquals(1, fake.correctCalls)
    }

    @Test
    fun aRetiredInitialCacheRequiresARealReadAndRemainsBlockedWhenThatReadFails() = edit { fake ->
        fake.fetchExpenseFailure = RepositoryException("Offline")
        val repository = object : ExpenseFactActions by fake {
            override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> =
                Result.failure(RepositoryException("The confirmed cache was retired"))
        }
        val initial = fake.baseExpense
        val vm = ExpenseFactViewModel(initial.id, repository, preferLocalCache = true)
        advanceUntilIdle()

        assertEquals(null, vm.uiState.value.expense, "No bound producer verified the retired route content")
        assertFalse(vm.uiState.value.authoritativeRootReady)
        assertFalse(vm.uiState.value.expenseStale, "Unverified route content is never presented as a known stale fact")
        assertEquals(ExpenseDetailDataLoadState.Failed, vm.uiState.value.expenseLoadState)
        assertEquals(1, fake.fetchExpenseCalls)

        fake.fetchExpenseFailure = null
        vm.retryLoadExpense()
        advanceUntilIdle()
        assertTrue(vm.uiState.value.authoritativeRootReady)
    }

    @Test
    fun aBindingChangeRetiresTheOldFloorAndRejectsItsLateInitialCache() = edit { fake ->
        val old = fake.baseExpense.copy(rowVersion = 7)
        fake.baseExpense = old
        fake.seedRefreshRequirement(11)
        fake.observeCorrections()
        val started = CompletableDeferred<Unit>()
        val cache = CompletableDeferred<Result<Expense>>()
        val repository = object : ExpenseFactActions by fake {
            override fun observeCorrections() = fake.correctionObservations
            override suspend fun fetchExpenseFromLocalCache(id: Long): Result<Expense> {
                started.complete(Unit)
                return cache.await()
            }
        }
        val vm = ExpenseFactViewModel(old.id, repository, preferLocalCache = true)
        advanceUntilIdle()
        assertTrue(started.isCompleted)

        val binding = fake.correctionBinding.copy(ledgerId = "another-ledger", bindingRevision = "another-binding")
        fake.baseExpense = old.copy(merchant = "Current binding", rowVersion = 1)
        fake.correctionObservations.value = fake.correctionObservations.value.copy(
            access = LedgerAccessContext(binding, true), corrections = emptyList())
        advanceUntilIdle()
        assertTrue(vm.uiState.value.authoritativeRootReady, "The old binding's receipt cannot block the new root")
        val current = vm.uiState.value
        cache.complete(Result.success(old.copy(rowVersion = 11)))
        advanceUntilIdle()

        assertEquals(current, vm.uiState.value)
        assertEquals(binding, vm.uiState.value.correctionAccess?.binding)
    }
}

private suspend fun FakeExpenseFactActions.seedRefreshRequirement(version: Long) {
    submitCorrection(correctionBinding, baseExpense, ExpenseCorrectionDraft("Original receipt", merchant = "Reviewed"))
        .getOrThrow()
    settleCorrection(PendingMutationStatus.Done)
    correctionObservations.value = correctionObservations.value.copy(corrections =
        correctionObservations.value.corrections.map { it.copy(row = it.row.copy(lastError = "correction_refresh_required:$version")) })
}

private fun FakeExpenseFactActions.clearRefreshRequirement() {
    correctionObservations.value = correctionObservations.value.copy(corrections =
        correctionObservations.value.corrections.map { it.copy(row = it.row.copy(lastError = null)) })
}
