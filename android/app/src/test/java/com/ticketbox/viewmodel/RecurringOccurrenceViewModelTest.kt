package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.repository.DebtActions
import com.ticketbox.data.repository.DebtListPage
import com.ticketbox.data.repository.LedgerAccessContext
import com.ticketbox.data.repository.LedgerActions
import com.ticketbox.data.repository.LogicalSessionBinding
import com.ticketbox.data.repository.OccurrencePaymentDraft
import com.ticketbox.data.repository.OutboxRow
import com.ticketbox.data.repository.PendingOccurrencePayment
import com.ticketbox.data.repository.RecurringOccurrenceActions
import com.ticketbox.data.repository.confirmedExpenseDtoFixture
import com.ticketbox.data.repository.toDomain
import com.ticketbox.domain.model.BatchApplyResult
import com.ticketbox.domain.model.ConfirmedStreamItem
import com.ticketbox.domain.model.CsvExport
import com.ticketbox.domain.model.Debt
import com.ticketbox.domain.model.DebtListLens
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.ui.screens.recurringItem
import java.lang.reflect.Proxy
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.cancelAndJoin
import kotlinx.coroutines.flow.Flow
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.flowOf
import kotlinx.coroutines.job
import kotlinx.coroutines.test.StandardTestDispatcher
import kotlinx.coroutines.test.advanceUntilIdle
import kotlinx.coroutines.test.resetMain
import kotlinx.coroutines.test.runTest
import kotlinx.coroutines.test.setMain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class RecurringOccurrenceViewModelTest {
    @Test
    fun refreshUpdatesFactsButSubmissionKeepsOriginalPaymentChoiceAndVersions() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        val payment = confirmedExpenseDtoFixture().toDomain().copy(rowVersion = 11L)
        val ledger = OccurrenceChoiceLedger(payment)
        val model = occurrenceModel(actions, ledger)
        try {
            model.open(recurringItem { rowVersion = 7L })
            advanceUntilIdle()
            assertTrue(model.uiState.value.canWrite)
            model.choose(model.uiState.value.payments.single() as ConfirmedStreamItem.ExpenseRow)
            val original = assertNotNull(model.uiState.value.choice)
            assertEquals(3L, original.request.expectedRowVersion)
            assertEquals(7L, original.request.expectedSeriesRowVersion)
            assertEquals(11L, original.request.expectedExpenseRowVersion)

            actions.occurrence = actions.occurrence.copy(rowVersion = 4L, seriesRowVersion = 8L)
            ledger.payment = payment.copy(rowVersion = 12L, merchant = "Updated payment")
            model.refresh()
            advanceUntilIdle()

            assertEquals(actions.occurrence, model.uiState.value.occurrence)
            assertEquals(12L, model.uiState.value.payments.single().root.rowVersion)
            assertEquals(original, model.uiState.value.choice)
            model.submit()
            advanceUntilIdle()

            assertEquals(listOf(actions.access.binding to original), actions.submissions)
            assertEquals(payment.publicId, actions.submissions.single().second.request.expensePublicId)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun unpaidPeriodWithoutConfirmedStreamUsesDebtListLedgerHome() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain(), emitConfirmedStream = false)
        val debts = OccurrenceChoiceDebts("CNY")
        val model = occurrenceModel(actions, ledger, debts)
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            assertEquals(emptyList<ConfirmedStreamItem>(), model.uiState.value.payments)
            assertEquals("CNY", model.uiState.value.ledgerHomeCurrencyCode)
            assertTrue(actions.submissions.isEmpty())
            assertEquals("unfulfilled", model.uiState.value.occurrence?.state)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun unpaidPeriodWithoutConfirmedStreamDoesNotGuessLedgerHomeWhenCapabilityMissing() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain(), emitConfirmedStream = false)
        val model = occurrenceModel(actions, ledger, OccurrenceChoiceDebts(ledgerHomeCurrencyCode = null))
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            assertNull(model.uiState.value.ledgerHomeCurrencyCode)
            assertTrue(actions.submissions.isEmpty())
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun conflictingDebtRecordAndCapabilityFailClosedWithoutGuessingLedgerHome() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain(), emitConfirmedStream = false)
        val debts = OccurrenceChoiceDebts(ledgerHomeCurrencyCode = "JPY", debts = listOf(periodDebt("CNY")))
        val model = occurrenceModel(actions, ledger, debts)
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "USD", merchant = "海外订阅"))
            advanceUntilIdle()
            assertNull(model.uiState.value.ledgerHomeCurrencyCode)
            assertTrue(actions.submissions.isEmpty())
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun openCanRestoreTheExactSavedPeriodInsteadOfCurrent() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val model = occurrenceModel(actions, OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain(), emitConfirmedStream = false))
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"), "2026-08")
            advanceUntilIdle()
            assertEquals("2026-08", model.uiState.value.requestedPeriod)
            assertEquals("2026-08", model.uiState.value.occurrence?.period)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }
}

private fun occurrenceModel(
    actions: OccurrenceChoiceActions,
    ledger: OccurrenceChoiceLedger,
    debts: OccurrenceChoiceDebts = OccurrenceChoiceDebts(),
) = RecurringOccurrenceViewModel(actions, ledger, debts)

private fun seedUnpaidAugust(actions: OccurrenceChoiceActions) {
    actions.occurrence = actions.occurrence.copy(
        period = "2026-08",
        homeCurrencyCode = "JPY",
        plannedAmountCents = 1200,
        reservedAmountCents = 1200,
    )
}

private fun periodDebt(homeCurrencyCode: String): Debt = Debt(
    publicId = "debt-$homeCurrencyCode",
    ledgerId = "owner",
    direction = "i_owe",
    counterpartyType = "external",
    counterpartyAccountId = null,
    counterpartyLabel = "对手方",
    principalAmountCents = 100_000,
    remainingAmountCents = 40_000,
    paidAmountCents = 60_000,
    status = "open",
    sourceType = "manual",
    sourceId = null,
    homeCurrencyCode = homeCurrencyCode,
    originalCurrencyCode = null,
    originalAmountMinor = null,
    createdAt = "2026-06-13T00:00:00Z",
    updatedAt = "2026-06-15T00:00:00Z",
    rowVersion = 1L,
)

private class OccurrenceChoiceDebts(
    var ledgerHomeCurrencyCode: String? = "CNY",
    var fail: Boolean = false,
    var debts: List<Debt> = emptyList(),
) : DebtActions by unsupportedOccurrenceDebtActions() {
    override suspend fun listDebts(lens: DebtListLens): Result<DebtListPage> {
        if (fail) return Result.failure(IllegalStateException("debts are offline"))
        return Result.success(DebtListPage(debts = debts, ledgerHomeCurrencyCode = ledgerHomeCurrencyCode))
    }
}

private fun unsupportedOccurrenceDebtActions(): DebtActions = requireNotNull(
    DebtActions::class.java.cast(
        Proxy.newProxyInstance(
            DebtActions::class.java.classLoader,
            arrayOf(DebtActions::class.java),
        ) { _, method, _ ->
            when (method.name) {
                "toString" -> "UnsupportedOccurrenceDebtActions"
                else -> throw UnsupportedOperationException(method.name)
            }
        },
    ),
)

private class OccurrenceChoiceActions : RecurringOccurrenceActions {
    val access = LedgerAccessContext(
        LogicalSessionBinding("https://occurrence.example", "ledger-1", "owner", "session", "binding"), true,
    )
    var occurrence = RecurringOccurrenceDto(
        seriesPublicId = "rec-1", period = "2026-09", seriesRowVersion = 7L, rowVersion = 3L,
        state = "unfulfilled", plannedAmountCents = 12_000L, reservedAmountCents = 12_000L,
        expensePublicId = null, paidAmountCents = null, nextDueDate = "2026-09-15", homeCurrencyCode = "CNY",
    )
    val submissions = mutableListOf<Pair<LogicalSessionBinding, OccurrencePaymentDraft>>()

    override fun currentAccess(): LedgerAccessContext = access
    override fun observeAccess(): Flow<LedgerAccessContext?> = flowOf(access)
    override fun describe(row: OutboxRow): PendingOccurrencePayment? = null
    override fun observeQueue(binding: LogicalSessionBinding): Flow<List<PendingOccurrencePayment>> = flowOf(emptyList())
    override suspend fun fetch(binding: LogicalSessionBinding, seriesId: String, period: String): Result<RecurringOccurrenceDto> =
        Result.success(if (period == "current") occurrence else occurrence.copy(period = period))

    override suspend fun enqueue(binding: LogicalSessionBinding, draft: OccurrencePaymentDraft): Result<Long> {
        submissions += binding to draft
        return Result.success(1L)
    }

    override suspend fun recover(binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean): Result<Unit> =
        error("Recovery is not part of an unsubmitted payment choice")
}

private class OccurrenceChoiceLedger(
    var payment: Expense,
    private val emitConfirmedStream: Boolean = true,
) : LedgerActions {
    private val rows = MutableStateFlow(
        if (emitConfirmedStream) listOf(payment.asPaymentRow()) else emptyList(),
    )
    override fun canModifyLedger(): Boolean = true
    override fun lastConfirmedSyncAt(): String? = null
    override fun observeConfirmed(): Flow<List<Expense>> = flowOf(if (emitConfirmedStream) listOf(payment) else emptyList())
    override fun observeConfirmedStream(): Flow<List<ConfirmedStreamItem>> = rows
    override suspend fun categories(): Result<List<String>> = error("Unexpected category read")
    override suspend fun tags(): Result<List<String>> = error("Unexpected tag read")
    override suspend fun months(): Result<List<String>> = error("Unexpected month read")

    override suspend fun syncConfirmed(month: String?, category: String?, tag: String?): Result<List<Expense>> {
        rows.value = if (emitConfirmedStream) listOf(payment.asPaymentRow()) else emptyList()
        return Result.success(if (emitConfirmedStream) listOf(payment) else emptyList())
    }

    override suspend fun exportConfirmedCsv(month: String?, category: String?, tag: String?): Result<CsvExport> =
        error("Unexpected export")
    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> =
        error("Period payment admits through ExpenseManualCreation")
    override suspend fun applyConfirmedBatch(
        expenses: List<Expense>, category: String?, tags: String?, reason: String,
    ): Result<BatchApplyResult> = error("Unexpected expense correction")
}

private fun Expense.asPaymentRow() = ConfirmedStreamItem.ExpenseRow(
    streamDate = "2026-09-01", streamAmountCents = requireNotNull(amountCents), root = this,
    lineageStatus = ExpenseLineageStatus.Confirmed, lineageHomeNetCents = requireNotNull(amountCents),
)
