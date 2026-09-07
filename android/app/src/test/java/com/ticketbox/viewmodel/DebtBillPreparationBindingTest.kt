package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.repository.DebtCreationQueueSnapshot
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.cancel
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.AfterTest
import kotlin.test.BeforeTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

/** The launcher suspends image preparation between the two existing ViewModel calls. */
class DebtBillPreparationBindingTest {
    private val dispatcher = StandardTestDispatcher()
    private lateinit var viewModel: DebtListViewModel

    @BeforeTest
    fun setUp() {
        Dispatchers.setMain(dispatcher)
    }

    @AfterTest
    fun tearDown() {
        if (::viewModel.isInitialized) viewModel.viewModelScope.cancel()
        Dispatchers.resetMain()
    }

    @Test
    fun preparedImageCannotBecomeANewHouseholdRecognitionRequest() = runTest(dispatcher) {
        val repo = FakeDebtActions(parseBillResult = Result.success(
            blankBillSuggestion().copy(merchant = "Original household bill", principalAmountCents = 12_000),
        ))
        repo.listCapability = "CNY"
        viewModel = DebtListViewModel(repo, repo.creation, repo.adjustments)
        advanceUntilIdle()
        assertTrue(viewModel.markBillParsePreparing())

        // Real UI preparation is still in IO while the live session changes.
        val original = requireNotNull(repo.creation.currentAccess())
        val next = original.copy(binding = original.binding.copy(ledgerId = "next-ledger", bindingRevision = "next-binding"))
        repo.creation.access.value = next
        repo.creation.pendingCreations.value = DebtCreationQueueSnapshot(next.binding)
        advanceUntilIdle()
        assertTrue(viewModel.state.value.homeCurrencyResolved)
        viewModel.updateDraftCounterparty("New household draft")
        viewModel.updateDraftAmount("88.00")

        // The original launcher's suspended preparation now returns the original bytes.
        viewModel.parseDebtBillImage("original.jpg", "image/jpeg", byteArrayOf(1, 2, 3))
        advanceUntilIdle()

        assertTrue(repo.parseBillCalls.isEmpty(), "Original bytes must not reach a request bound to the new household")
        assertEquals("New household draft", viewModel.state.value.addDraft.counterpartyLabel)
        assertEquals("88.00", viewModel.state.value.addDraft.amountYuanInput)
        assertFalse(viewModel.state.value.pendingBillParsePrefill)
        assertFalse(viewModel.state.value.isParsingBill)
        assertTrue(repo.creation.createDrafts.isEmpty())
    }
}
