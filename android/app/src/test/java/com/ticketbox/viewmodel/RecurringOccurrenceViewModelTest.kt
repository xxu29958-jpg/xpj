package com.ticketbox.viewmodel

import androidx.lifecycle.viewModelScope
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
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
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.domain.model.ExpenseLineageStatus
import com.ticketbox.ui.screens.recurringItem
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
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
class RecurringOccurrenceViewModelTest {
    @Test
    fun refreshUpdatesFactsButSubmissionKeepsOriginalPaymentChoiceAndVersions() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        val payment = confirmedExpenseDtoFixture().toDomain().copy(rowVersion = 11L)
        val ledger = OccurrenceChoiceLedger(payment)
        val model = RecurringOccurrenceViewModel(actions, ledger)
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
}

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
        Result.success(occurrence)

    override suspend fun enqueue(binding: LogicalSessionBinding, draft: OccurrencePaymentDraft): Result<Long> {
        submissions += binding to draft
        return Result.success(1L)
    }

    override suspend fun recover(binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean): Result<Unit> =
        error("Recovery is not part of an unsubmitted payment choice")
}

private class OccurrenceChoiceLedger(var payment: Expense) : LedgerActions {
    private val rows = MutableStateFlow<List<ConfirmedStreamItem>>(listOf(payment.asPaymentRow()))
    override fun canModifyLedger(): Boolean = true
    override fun lastConfirmedSyncAt(): String? = null
    override fun observeConfirmed(): Flow<List<Expense>> = flowOf(listOf(payment))
    override fun observeConfirmedStream(): Flow<List<ConfirmedStreamItem>> = rows
    override suspend fun categories(): Result<List<String>> = error("Unexpected category read")
    override suspend fun tags(): Result<List<String>> = error("Unexpected tag read")
    override suspend fun months(): Result<List<String>> = error("Unexpected month read")

    override suspend fun syncConfirmed(month: String?, category: String?, tag: String?): Result<List<Expense>> {
        rows.value = listOf(payment.asPaymentRow())
        return Result.success(listOf(payment))
    }

    override suspend fun exportConfirmedCsv(month: String?, category: String?, tag: String?): Result<CsvExport> =
        error("Unexpected export")
    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> = error("Unexpected expense creation")
    override suspend fun applyConfirmedBatch(
        expenses: List<Expense>, category: String?, tags: String?, reason: String,
    ): Result<BatchApplyResult> = error("Unexpected expense correction")

}

private fun Expense.asPaymentRow() = ConfirmedStreamItem.ExpenseRow(
    streamDate = "2026-09-01", streamAmountCents = requireNotNull(amountCents), root = this,
    lineageStatus = ExpenseLineageStatus.Confirmed, lineageHomeNetCents = requireNotNull(amountCents),
)
