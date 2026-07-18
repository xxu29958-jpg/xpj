package com.ticketbox.viewmodel

import com.ticketbox.data.repository.BillSplitActions
import com.ticketbox.data.repository.BillSplitLedgerActions
import com.ticketbox.domain.model.BillSplitInbox
import com.ticketbox.domain.model.BillSplitSent
import com.ticketbox.domain.model.BillSplitStatusValues
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.LEDGER_ROLE_OWNER
import com.ticketbox.domain.model.LedgerSummary
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
import kotlin.test.assertNotNull
import kotlin.test.assertFalse

@OptIn(ExperimentalCoroutinesApi::class)
class BillSplitViewModelTest {

    private fun billSplitTest(block: suspend TestScope.() -> Unit) = runTest {
        val dispatcher = StandardTestDispatcher(testScheduler)
        Dispatchers.setMain(dispatcher)
        try {
            block()
        } finally {
            Dispatchers.resetMain()
        }
    }

    @Test
    fun initialFailureMarksBothListsFailedWithoutFabricatingEmpty() = billSplitTest {
        val fake = FakeBillSplitActions(
            inboxResult = Result.failure(IllegalStateException("inbox offline")),
            sentResult = Result.failure(IllegalStateException("sent offline")),
        )
        val vm = BillSplitViewModel(fake, FakeBillSplitLedgerActions())

        vm.refresh()
        advanceUntilIdle()

        assertEquals(emptyList(), vm.uiState.value.inbox)
        assertEquals(emptyList(), vm.uiState.value.sent)
        assertEquals(BillSplitListLoadState.Failed, vm.uiState.value.inboxLoadState)
        assertEquals(BillSplitListLoadState.Failed, vm.uiState.value.sentLoadState)
        assertNotNull(vm.uiState.value.message)
    }

    @Test
    fun inboxLoadedEmptyAndSentFailureRemainIndependent() = billSplitTest {
        val fake = FakeBillSplitActions(
            inboxResult = Result.success(emptyList()),
            sentResult = Result.failure(IllegalStateException("sent offline")),
        )
        val vm = BillSplitViewModel(fake, FakeBillSplitLedgerActions())

        vm.refresh()
        advanceUntilIdle()

        assertEquals(BillSplitListLoadState.Loaded, vm.uiState.value.inboxLoadState)
        assertEquals(BillSplitListLoadState.Failed, vm.uiState.value.sentLoadState)
        assertEquals(emptyList(), vm.uiState.value.inbox)
        assertEquals(emptyList(), vm.uiState.value.sent)
    }

    @Test
    fun refreshFailureKeepsExistingRowsAndMarksListsFailed() = billSplitTest {
        val fake = FakeBillSplitActions(
            inboxResult = Result.success(listOf(inboxInvite())),
            sentResult = Result.success(listOf(sentInvite())),
        )
        val vm = BillSplitViewModel(fake, FakeBillSplitLedgerActions())

        vm.refresh()
        advanceUntilIdle()

        fake.inboxResult = Result.failure(IllegalStateException("inbox offline"))
        fake.sentResult = Result.failure(IllegalStateException("sent offline"))
        vm.refresh()
        advanceUntilIdle()

        assertEquals(listOf(inboxInvite()), vm.uiState.value.inbox)
        assertEquals(listOf(sentInvite()), vm.uiState.value.sent)
        assertEquals(BillSplitListLoadState.Failed, vm.uiState.value.inboxLoadState)
        assertEquals(BillSplitListLoadState.Failed, vm.uiState.value.sentLoadState)
    }

    @Test
    fun cachedAndRefreshedLedgersPopulateAcceptTargets() = billSplitTest {
        val ledgerActions = FakeBillSplitLedgerActions(
            cached = listOf(ledger("cached", "Cached ledger")),
            refreshResult = Result.success(listOf(ledger("fresh", "Fresh ledger"))),
        )
        val vm = BillSplitViewModel(FakeBillSplitActions(), ledgerActions)

        assertEquals(listOf(BillSplitTargetLedger("cached", "Cached ledger")), vm.uiState.value.candidateTargetLedgers)

        vm.refresh()
        advanceUntilIdle()

        assertEquals(listOf(BillSplitTargetLedger("fresh", "Fresh ledger")), vm.uiState.value.candidateTargetLedgers)
    }

    @Test
    fun viewerCannotCancelSentInvitation() = billSplitTest {
        val fake = FakeBillSplitActions(canModify = false)
        val vm = BillSplitViewModel(fake, FakeBillSplitLedgerActions())

        vm.cancel("split_out_1")
        advanceUntilIdle()

        assertFalse(vm.uiState.value.canModify)
        assertEquals(0, fake.cancelCalls)
        assertNotNull(vm.uiState.value.message)
    }
}

private class FakeBillSplitActions(
    var inboxResult: Result<List<BillSplitInbox>> = Result.success(emptyList()),
    var sentResult: Result<List<BillSplitSent>> = Result.success(emptyList()),
    private val canModify: Boolean = true,
) : BillSplitActions {
    var cancelCalls: Int = 0
        private set

    override fun canModifyLedger(): Boolean = canModify

    override suspend fun fetchBillSplitInbox(): Result<List<BillSplitInbox>> = inboxResult

    override suspend fun fetchBillSplitSent(): Result<List<BillSplitSent>> = sentResult

    override suspend fun acceptBillSplitInvitation(
        publicId: String,
        targetLedgerId: String,
    ): Result<BillSplitInbox> = Result.success(inboxInvite(publicId = publicId))

    override suspend fun rejectBillSplitInvitation(publicId: String): Result<BillSplitInbox> =
        Result.success(inboxInvite(publicId = publicId, status = BillSplitStatusValues.REJECTED))

    override suspend fun cancelBillSplitInvitation(publicId: String): Result<BillSplitSent> {
        cancelCalls += 1
        return Result.success(sentInvite(publicId = publicId, status = BillSplitStatusValues.CANCELLED))
    }
}

private class FakeBillSplitLedgerActions(
    private val cached: List<LedgerSummary> = emptyList(),
    var refreshResult: Result<List<LedgerSummary>> = Result.success(emptyList()),
) : BillSplitLedgerActions {
    override fun cachedLedgers(): List<LedgerSummary> = cached

    override suspend fun refreshLedgers(): Result<List<LedgerSummary>> = refreshResult
}

private fun ledger(ledgerId: String, name: String): LedgerSummary = LedgerSummary(
    ledgerId = ledgerId,
    name = name,
    role = LEDGER_ROLE_OWNER,
    isDefault = true,
    homeCurrency = com.ticketbox.domain.model.CurrencyCode.CNY,
)

private fun inboxInvite(
    publicId: String = "split_in_1",
    status: String = BillSplitStatusValues.INVITED,
): BillSplitInbox = BillSplitInbox(
    publicId = publicId,
    status = status,
    amountCents = 1200,
    homeCurrency = CurrencyCode.CNY,
    originalCurrency = CurrencyCode.CNY,
    originalAmountMinor = 1200L,
    exchangeRateToHome = null,
    exchangeRateDate = null,
    exchangeRateSource = null,
    merchantSnapshot = "Cafe",
    categorySuggestion = "Food",
    expenseTimeSnapshot = "2026-07-01T00:00:00Z",
    expiresAt = "2026-08-01T00:00:00Z",
    createdAt = "2026-07-01T00:00:00Z",
    acceptedAt = null,
    rejectedAt = null,
    cancelledAt = null,
    expiredAt = null,
    senderAccountId = 10,
    senderDisplayName = "Sender",
)

private fun sentInvite(
    publicId: String = "split_out_1",
    status: String = BillSplitStatusValues.INVITED,
): BillSplitSent = BillSplitSent(
    publicId = publicId,
    status = status,
    amountCents = 1200,
    homeCurrency = CurrencyCode.CNY,
    originalCurrency = CurrencyCode.CNY,
    originalAmountMinor = 1200L,
    exchangeRateToHome = null,
    exchangeRateDate = null,
    exchangeRateSource = null,
    merchantSnapshot = "Cafe",
    categorySuggestion = "Food",
    expenseTimeSnapshot = "2026-07-01T00:00:00Z",
    expiresAt = "2026-08-01T00:00:00Z",
    createdAt = "2026-07-01T00:00:00Z",
    acceptedAt = null,
    rejectedAt = null,
    cancelledAt = null,
    expiredAt = null,
    receiverAccountId = 20,
    receiverDisplayNameSnapshot = "Receiver",
    senderExpenseId = 30,
)
