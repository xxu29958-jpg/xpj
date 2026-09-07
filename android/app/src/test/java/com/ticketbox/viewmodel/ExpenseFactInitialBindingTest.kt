package com.ticketbox.viewmodel

import com.ticketbox.data.repository.ExpenseFactActions
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
        val vm = ExpenseFactViewModel(oldRoot.id, repository, initialExpense = oldRoot)
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
    }
}
