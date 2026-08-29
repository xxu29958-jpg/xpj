package com.ticketbox.viewmodel

import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.advanceUntilIdle

/** A1: repayment capture is consumed by the confirmed fact owner, not the legacy editor. */
@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseFactViewModelRepaymentTest : ExpenseFactViewModelTestBase() {
    @Test
    fun `successful capture opens the real review destination once`() = edit { fake ->
        fake.repaymentDraftResult = { Result.success(fake.repaymentDraft()) }
        val vm = viewModel(fake)

        vm.createRepaymentDraftFromExpense()
        advanceUntilIdle()

        assertEquals(1, fake.repaymentDraftCalls)
        assertEquals(fake.baseExpense, fake.repaymentDraftExpense)
        assertFalse(vm.uiState.value.repaymentDraftCreating)
        assertEquals("rd-1", vm.consumeOpenRepaymentDraftPublicId())
        assertNull(vm.consumeOpenRepaymentDraftPublicId())
    }

    @Test
    fun `read only fact never starts repayment capture`() = edit { fake ->
        fake.canModifyLedgerFlag = false
        val vm = viewModel(fake)

        vm.createRepaymentDraftFromExpense()
        advanceUntilIdle()

        assertEquals(0, fake.repaymentDraftCalls)
        assertNull(vm.uiState.value.openRepaymentDraftPublicId)
    }
}
