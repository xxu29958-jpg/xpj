package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.ExpenseFactActions
import com.ticketbox.data.repository.LogicalSessionBinding
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.job
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.RepositoryException
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactInitialBindingTest : ExpenseFactViewModelTestBase() {
    @Test
    fun firstBindingCannotAdoptAnUnboundRouteRootFromAnotherServer() = edit { fake ->
        val oldRoot = fake.baseExpense.copy(rowVersion = 100, merchant = "Old server fact")
        val currentRoot = oldRoot.copy(publicId = "current-server-fact", rowVersion = 1, merchant = "Current server fact")
        fake.baseExpense = currentRoot
        fake.fetchExpenseFailure = RepositoryException("Offline")
        val repository = object : ExpenseFactActions by fake {
            override fun observeCorrections() = fake.correctionObservations
        }
        val vm = ExpenseFactViewModel(oldRoot.id, repository, preferLocalCache = true)
        try {
            advanceUntilIdle()
            assertFalse(vm.uiState.value.authoritativeRootReady)
            val binding = fake.correctionBinding.copy(serverUrl = "https://replacement.example.test",
                sessionGeneration = "replacement-session", bindingRevision = "replacement-binding")
            fake.correctionObservations.value = fake.correctionObservations.value.copy(access = LedgerAccessContext(binding, true))
            advanceUntilIdle()

            assertEquals(currentRoot, vm.uiState.value.expense, "An unbound route root has no comparable revision in the current server")
            assertEquals(binding, vm.uiState.value.correctionAccess?.binding)
            assertTrue(vm.uiState.value.authoritativeRootReady)
            assertEquals(0, fake.fetchExpenseCalls, "The current bound cache supports offline adoption")
            vm.openCorrectionSheet()
            assertEquals(currentRoot, vm.correctionBaseline)
            assertEquals(binding, vm.correctionBinding)
        } finally {
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }


    @Test
    fun lateRecoveryFailureCannotOverwriteTheReplacementBinding() = edit { fake ->
        fake.observeCorrections()
        val response = CompletableDeferred<Result<Unit>>()
        val started = CompletableDeferred<Unit>()
        val repository = object : ExpenseFactActions by fake {
            override fun observeCorrections() = fake.correctionObservations
            override suspend fun recoverCorrection(expectedBinding: LogicalSessionBinding, rowId: Long, drop: Boolean): Result<Unit> {
                started.complete(Unit)
                return response.await()
            }
        }
        val vm = ExpenseFactViewModel(fake.baseExpense.id, repository)
        try {
            advanceUntilIdle()
            vm.recoverCorrection(99, drop = true)
            advanceUntilIdle()
            assertTrue(started.isCompleted)
            val replacement = fake.correctionBinding.copy(ledgerId = "replacement", bindingRevision = "replacement-binding")
            fake.baseExpense = fake.baseExpense.copy(publicId = "replacement-root", merchant = "Current ledger")
            fake.correctionObservations.value = fake.correctionObservations.value.copy(access = LedgerAccessContext(replacement, true))
            advanceUntilIdle()
            val current = vm.uiState.value
            assertEquals(replacement, current.correctionAccess?.binding)
            assertFalse(current.correctionRecoveryBusy)
            response.complete(Result.failure(RepositoryException("Old recovery failure")))
            advanceUntilIdle()
            assertEquals(current, vm.uiState.value)
        } finally {
            response.complete(Result.success(Unit))
            vm.viewModelScope.coroutineContext.job.cancelAndJoin()
        }
    }
}
