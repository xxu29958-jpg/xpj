package com.ticketbox.viewmodel

import androidx.lifecycle.SavedStateHandle
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.repository.ExpenseCommandAcceptance
import com.ticketbox.domain.model.UiText
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.TestScope
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseEditViewModelOcrCommandTest {
    private fun edit(block: suspend TestScope.(FakeExpenseEditActions) -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block(FakeExpenseEditActions())
        } finally {
            advanceUntilIdle()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun confirmedDropOfFailedOcrRegionUnlocksResubmissionAndPreservesForm() = edit { fake ->
        val savedState = SavedStateHandle()
        val vm = ExpenseEditViewModel(expenseId = 7L, repository = fake, savedState = savedState)
        advanceUntilIdle()
        val originalExpense = vm.uiState.value.expense
        val originalFormRevision = vm.uiState.value.formRevision

        fake.retryOcrResult = Result.success(ExpenseCommandAcceptance(fake.baseExpense, listOf(11L)))
        vm.retryOcr()
        advanceUntilIdle()
        assertEquals(1, fake.retryOcrCalls)
        assertEquals(listOf(11L), vm.uiState.value.commandRowIds)

        fake.commands.value = fake.commands.value.copy(
            commands = listOf(
                observedExpenseCommand(
                    11L,
                    fake.baseExpense,
                    PendingMutationType.RetryOcr,
                    PendingMutationStatus.Failed,
                    fake.binding,
                ).let { cmd -> cmd.copy(row = cmd.row.copy(lastError = "ocr_region_no_text")) },
            ),
        )
        advanceUntilIdle()
        assertEquals(UiText.res(R.string.ocr_region_no_text_recovery), vm.uiState.value.message)

        // An arbitrary empty observation without an explicit user drop must NOT unlock resubmission.
        fake.commands.value = fake.commands.value.copy(commands = emptyList(), droppedRowIds = emptySet())
        advanceUntilIdle()
        assertEquals(listOf(11L), vm.uiState.value.commandRowIds)
        vm.retryOcr()
        advanceUntilIdle()
        assertEquals(1, fake.retryOcrCalls)
        assertEquals(UiText.res(R.string.expense_command_needs_attention), vm.uiState.value.message)

        // Confirmed drop from Sync & Todos clears the blocked command id and SavedState while keeping the form.
        fake.commands.value = fake.commands.value.copy(commands = emptyList(), droppedRowIds = setOf(11L))
        advanceUntilIdle()
        assertTrue(vm.uiState.value.commandRowIds.isEmpty())
        assertNull(savedState.get<LongArray>("expense_command_ids"))
        assertNull(savedState.get<String>("expense_command_binding"))
        assertEquals(originalExpense, vm.uiState.value.expense)
        assertEquals(originalFormRevision, vm.uiState.value.formRevision)

        // A new region selection can now be submitted cleanly from the same editor session.
        fake.retryOcrResult = Result.success(ExpenseCommandAcceptance(fake.baseExpense, listOf(12L)))
        vm.retryOcr()
        advanceUntilIdle()
        assertEquals(2, fake.retryOcrCalls)
        assertEquals(listOf(12L), vm.uiState.value.commandRowIds)
    }

    @Test
    fun droppingFailedPatchDoesNotUnlockEditorWithStaleOptimisticBaseline() = edit { fake ->
        val savedState = SavedStateHandle()
        val vm = ExpenseEditViewModel(expenseId = 7L, repository = fake, savedState = savedState)
        advanceUntilIdle()

        val optimistic = fake.baseExpense.copy(merchant = "B")
        fake.saveOfflineResponder = { _, _, _ -> Result.success(ExpenseCommandAcceptance(optimistic, listOf(21L))) }
        vm.save(
            com.ticketbox.domain.model.ExpenseDraft(
                amountCents = 1000L,
                originalCurrencyCode = com.ticketbox.domain.model.CurrencyCode.CNY,
                originalAmountMinor = 1000L,
                merchant = "B",
                category = "其他",
                note = null,
                expenseTime = null,
                tags = null,
                valueScore = null,
                regretScore = null,
            ),
        )
        advanceUntilIdle()
        assertEquals(listOf(21L), vm.uiState.value.commandRowIds)
        assertEquals(false, vm.uiState.value.commandAllowsDropUnlock)

        // Even if droppedRowIds reports the patch id, a mutating PATCH must NOT unlock with optimistic merchant "B".
        fake.commands.value = fake.commands.value.copy(commands = emptyList(), droppedRowIds = setOf(21L))
        advanceUntilIdle()
        assertEquals(listOf(21L), vm.uiState.value.commandRowIds)
        assertEquals(1, fake.saveCalls)
    }

    @Test
    fun processRestoreUnlocksDroppedRetryOcrFromDurableAbandonedObservation() = edit { fake ->
        val savedState = SavedStateHandle()
        val beforeDeath = ExpenseEditViewModel(expenseId = 7L, repository = fake, savedState = savedState)
        advanceUntilIdle()

        fake.retryOcrResult = Result.success(ExpenseCommandAcceptance(fake.baseExpense, listOf(31L)))
        beforeDeath.retryOcr()
        advanceUntilIdle()
        assertEquals(listOf(31L), savedState.get<LongArray>("expense_command_ids")?.toList())
        assertEquals(true, savedState.get<Boolean>("expense_command_drop_unlock"))

        // Process dies after user drops RetryOcr #31 in Sync & Todos (Room persisted status='abandoned').
        val restoredFake = FakeExpenseEditActions().apply {
            commands.value = commands.value.copy(commands = emptyList(), droppedRowIds = setOf(31L))
            retryOcrResult = Result.success(ExpenseCommandAcceptance(baseExpense, listOf(32L)))
        }
        val restored = ExpenseEditViewModel(expenseId = 7L, repository = restoredFake, savedState = savedState)
        advanceUntilIdle()

        assertTrue(restored.uiState.value.commandRowIds.isEmpty())
        assertEquals(false, restored.uiState.value.commandAllowsDropUnlock)
        assertNull(savedState.get<LongArray>("expense_command_ids"))
        assertNull(savedState.get<String>("expense_command_binding"))
        assertNull(savedState.get<Boolean>("expense_command_drop_unlock"))

        restored.retryOcr()
        advanceUntilIdle()
        assertEquals(1, restoredFake.retryOcrCalls)
        assertEquals(listOf(32L), restored.uiState.value.commandRowIds)
    }

    @Test
    fun legacyBaselineSavedStateWithoutDropUnlockFlagUnlocksDroppedRetryOcr() = edit { _ ->
        val baselineFake = FakeExpenseEditActions()
        val legacySavedState = SavedStateHandle(
            mapOf(
                "expense_command_ids" to longArrayOf(41L),
                "expense_command_binding" to com.ticketbox.data.repository.logicalBindingAdapter.toJson(baselineFake.binding),
            ),
        )
        baselineFake.commands.value = baselineFake.commands.value.copy(
            commands = emptyList(),
            droppedRowIds = setOf(41L),
        )
        baselineFake.retryOcrResult = Result.success(ExpenseCommandAcceptance(baselineFake.baseExpense, listOf(42L)))

        val restored = ExpenseEditViewModel(expenseId = 7L, repository = baselineFake, savedState = legacySavedState)
        advanceUntilIdle()

        assertTrue(restored.uiState.value.commandRowIds.isEmpty())
        assertEquals(false, restored.uiState.value.commandAllowsDropUnlock)
        assertNull(legacySavedState.get<LongArray>("expense_command_ids"))
        assertNull(legacySavedState.get<String>("expense_command_binding"))
        assertNull(legacySavedState.get<Boolean>("expense_command_drop_unlock"))

        restored.retryOcr()
        advanceUntilIdle()
        assertEquals(1, baselineFake.retryOcrCalls)
        assertEquals(listOf(42L), restored.uiState.value.commandRowIds)
    }
}
