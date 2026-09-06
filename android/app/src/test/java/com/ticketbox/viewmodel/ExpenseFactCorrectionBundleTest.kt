package com.ticketbox.viewmodel

import com.ticketbox.data.repository.RepositoryException
import com.ticketbox.data.repository.expenseFactBundleDtoFixture
import com.ticketbox.data.repository.toDomain
import com.ticketbox.data.local.PendingMutationStatus
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactCorrectionBundleTest : ExpenseFactViewModelTestBase() {
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
}
