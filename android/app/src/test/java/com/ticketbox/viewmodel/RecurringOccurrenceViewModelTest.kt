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

    @Test
    fun unpaidPeriodRecordPaymentCapturesOriginWithoutQueuingFulfillment() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        actions.occurrence = actions.occurrence.copy(
            period = "2026-08",
            homeCurrencyCode = "JPY",
            plannedAmountCents = 1200,
            reservedAmountCents = 1200,
        )
        val model = RecurringOccurrenceViewModel(actions, OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain()))
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            model.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(actions.access.binding, origin.binding)
            assertEquals("rec-1", origin.seriesPublicId)
            assertEquals("2026-08", origin.period)
            assertEquals("日元订阅", origin.merchant)
            assertEquals("JPY", origin.obligationCurrencyCode)
            assertEquals(1200L, origin.plannedAmountCents)
            assertTrue(origin.clientRef.isNotBlank())
            assertTrue(actions.submissions.isEmpty())
            assertEquals("unfulfilled", model.uiState.value.occurrence?.state)
            assertEquals(1200L, model.uiState.value.occurrence?.reservedAmountCents)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun recreationKeepsPeriodPaymentCategoryNoteCurrencyAmountClientRefSeriesAndPeriod() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val model = RecurringOccurrenceViewModel(actions, OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain()))
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            model.recordPeriodPayment()
            val first = assertNotNull(model.uiState.value.periodPaymentOrigin)
            val capture = RecurringOccurrenceViewModel::class.members.firstOrNull { it.name == "capturePeriodPaymentDraft" }
            assertNotNull(capture, "User-entered category and note must stay on the captured origin across recreation")
            capture.call(model, "订阅", "八月义务", "JPY", 1300L)
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            val restored = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(first.clientRef, restored.clientRef)
            assertEquals("rec-1", restored.seriesPublicId)
            assertEquals("2026-08", restored.period)
            assertEquals("JPY", restored.obligationCurrencyCode)
            assertEquals("订阅", originField(restored, "category"))
            assertEquals("八月义务", originField(restored, "note"))
            assertEquals(1300L, originField(restored, "capturedAmountCents") ?: restored.plannedAmountCents)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun offlineAfterLoadAdmitsPaymentFromCapturedOriginWithoutRereadingSeriesOrDebts() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain().copy(homeCurrencyCode = "CNY"))
        val model = RecurringOccurrenceViewModel(actions, ledger)
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            val fetchesAfterLoad = actions.fetchCount
            val syncsAfterLoad = ledger.syncCount
            actions.failReads = true
            ledger.failSync = true
            model.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(fetchesAfterLoad, actions.fetchCount)
            assertEquals(syncsAfterLoad, ledger.syncCount)
            assertEquals(actions.access.binding, origin.binding)
            assertEquals("JPY", origin.obligationCurrencyCode)
            assertEquals("2026-08", origin.period)
            assertTrue(origin.clientRef.isNotBlank())
            assertEquals("CNY", originField(origin, "ledgerHomeCurrencyCode"))
            assertTrue(actions.submissions.isEmpty())
            val admitted = ledger.createManualExpense(
                ExpenseDraft(
                    amountCents = null,
                    originalCurrencyCode = com.ticketbox.domain.model.CurrencyCode.JPY,
                    originalAmountMinor = 1200,
                    merchant = origin.merchant,
                    category = "订阅",
                    note = "八月义务",
                    expenseTime = "2026-09-03T10:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                    ledgerHomeCurrency = com.ticketbox.domain.model.CurrencyCode.CNY,
                    clientRef = origin.clientRef,
                ),
            )
            assertTrue(admitted.isSuccess)
            assertEquals(listOf(origin.clientRef), ledger.createdClientRefs)
            assertEquals(fetchesAfterLoad, actions.fetchCount)
            assertEquals(syncsAfterLoad, ledger.syncCount)
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun unknownObligationCurrencyDoesNotGuessLedgerHomeForTheBaselineAmount() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        actions.occurrence = actions.occurrence.copy(homeCurrencyCode = null)
        val model = RecurringOccurrenceViewModel(actions, OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain()))
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = null, merchant = "旧订阅"))
            advanceUntilIdle()
            model.recordPeriodPayment()
            val origin = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertNull(origin.obligationCurrencyCode)
            assertEquals(1200L, origin.plannedAmountCents)
            assertNull(com.ticketbox.domain.model.CurrencyCode.fromStorageKeyOrNull(origin.obligationCurrencyCode))
            assertTrue(actions.submissions.isEmpty())
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }

    @Test
    fun roomAcceptedCreateReentryReusesOriginalClientRef() = runTest {
        Dispatchers.setMain(StandardTestDispatcher(testScheduler))
        val actions = OccurrenceChoiceActions()
        seedUnpaidAugust(actions)
        val ledger = OccurrenceChoiceLedger(confirmedExpenseDtoFixture().toDomain())
        val model = RecurringOccurrenceViewModel(actions, ledger)
        try {
            model.open(recurringItem { rowVersion = 7L }.copy(homeCurrencyCode = "JPY", merchant = "日元订阅"))
            advanceUntilIdle()
            model.recordPeriodPayment()
            val original = assertNotNull(model.uiState.value.periodPaymentOrigin).clientRef
            ledger.createManualExpense(
                ExpenseDraft(
                    amountCents = 1200,
                    merchant = "日元订阅",
                    category = "订阅",
                    note = "八月义务",
                    expenseTime = "2026-09-03T10:00:00Z",
                    tags = null,
                    valueScore = null,
                    regretScore = null,
                    clientRef = original,
                ),
            ).getOrThrow()
            model.dismissPeriodPayment()
            model.recordPeriodPayment()
            val reentered = assertNotNull(model.uiState.value.periodPaymentOrigin)
            assertEquals(original, reentered.clientRef)
            assertEquals(listOf(original), ledger.createdClientRefs)
            assertTrue(actions.submissions.isEmpty())
        } finally {
            model.viewModelScope.coroutineContext.job.cancelAndJoin()
            Dispatchers.resetMain()
        }
    }
}

private fun seedUnpaidAugust(actions: OccurrenceChoiceActions) {
    actions.occurrence = actions.occurrence.copy(
        period = "2026-08",
        homeCurrencyCode = "JPY",
        plannedAmountCents = 1200,
        reservedAmountCents = 1200,
    )
}

private fun originField(origin: RecurringPeriodPaymentOrigin, name: String): Any? =
    RecurringPeriodPaymentOrigin::class.members.firstOrNull { it.name == name }?.call(origin)

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
    var fetchCount = 0
    var failReads = false

    override fun currentAccess(): LedgerAccessContext = access
    override fun observeAccess(): Flow<LedgerAccessContext?> = flowOf(access)
    override fun describe(row: OutboxRow): PendingOccurrencePayment? = null
    override fun observeQueue(binding: LogicalSessionBinding): Flow<List<PendingOccurrencePayment>> = flowOf(emptyList())
    override suspend fun fetch(binding: LogicalSessionBinding, seriesId: String, period: String): Result<RecurringOccurrenceDto> {
        fetchCount++
        if (failReads) return Result.failure(IllegalStateException("series read is offline"))
        return Result.success(occurrence)
    }

    override suspend fun enqueue(binding: LogicalSessionBinding, draft: OccurrencePaymentDraft): Result<Long> {
        submissions += binding to draft
        return Result.success(1L)
    }

    override suspend fun recover(binding: LogicalSessionBinding, row: OutboxRow, drop: Boolean): Result<Unit> =
        error("Recovery is not part of an unsubmitted payment choice")
}

private class OccurrenceChoiceLedger(var payment: Expense) : LedgerActions {
    private val rows = MutableStateFlow<List<ConfirmedStreamItem>>(listOf(payment.asPaymentRow()))
    val createdClientRefs = mutableListOf<String>()
    var syncCount = 0
    var failSync = false
    override fun canModifyLedger(): Boolean = true
    override fun lastConfirmedSyncAt(): String? = null
    override fun observeConfirmed(): Flow<List<Expense>> = flowOf(listOf(payment))
    override fun observeConfirmedStream(): Flow<List<ConfirmedStreamItem>> = rows
    override suspend fun categories(): Result<List<String>> = error("Unexpected category read")
    override suspend fun tags(): Result<List<String>> = error("Unexpected tag read")
    override suspend fun months(): Result<List<String>> = error("Unexpected month read")

    override suspend fun syncConfirmed(month: String?, category: String?, tag: String?): Result<List<Expense>> {
        syncCount++
        if (failSync) return Result.failure(IllegalStateException("confirmed stream is offline"))
        rows.value = listOf(payment.asPaymentRow())
        return Result.success(listOf(payment))
    }

    override suspend fun exportConfirmedCsv(month: String?, category: String?, tag: String?): Result<CsvExport> =
        error("Unexpected export")
    override suspend fun createManualExpense(draft: ExpenseDraft): Result<Expense> {
        val ref = draft.clientRef?.takeIf { it.isNotBlank() } ?: return Result.failure(IllegalStateException("period payment must reuse the captured clientRef"))
        createdClientRefs += ref
        return Result.success(payment.copy(clientRef = ref, pendingSync = true))
    }
    override suspend fun applyConfirmedBatch(
        expenses: List<Expense>, category: String?, tags: String?, reason: String,
    ): Result<BatchApplyResult> = error("Unexpected expense correction")

}

private fun Expense.asPaymentRow() = ConfirmedStreamItem.ExpenseRow(
    streamDate = "2026-09-01", streamAmountCents = requireNotNull(amountCents), root = this,
    lineageStatus = ExpenseLineageStatus.Confirmed, lineageHomeNetCents = requireNotNull(amountCents),
)
