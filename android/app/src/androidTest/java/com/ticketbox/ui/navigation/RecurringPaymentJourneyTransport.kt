package com.ticketbox.ui.navigation

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.repository.CreateExpenseDispatcher
import com.ticketbox.data.repository.ExpenseCorrectionConnectedFixture
import com.ticketbox.data.repository.CorrectionConnectedNetwork
import com.ticketbox.data.repository.OutboxDrainEngine
import com.ticketbox.data.repository.RecurringOccurrenceDispatcher
import com.ticketbox.data.repository.toEntity
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.DebtListResponseDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemListResponseDto
import com.ticketbox.data.remote.dto.RecurringOccurrenceDto
import com.ticketbox.data.remote.dto.RecurringOccurrencePaymentRequestDto
import com.ticketbox.domain.model.ExpenseSourceValues
import java.util.concurrent.CopyOnWriteArrayList

internal class RecurringPaymentJourneyTransport {
    var fulfilled = false
    var recording = false
    var recordedCurrency: String? = "JPY"
    lateinit var network: CorrectionConnectedNetwork
    private lateinit var service: ApiService
    private var fxTask = BackgroundTaskDto("payment-fx", "expense_fx", "running",
        createdAt = "2026-09-12T00:00:00Z", sourceExpenseId = 42)
    private var original: ExpenseDto? = null
    val created: Boolean get() = original != null

    suspend fun drain(fixture: ExpenseCorrectionConnectedFixture) {
        val adapters = OutboxAdapterGraph()
        OutboxDrainEngine(fixture.outbox, listOf(
            CreateExpenseDispatcher({ service }, adapters.manualCreateAdapter) { ledger, clientRef, created ->
                fixture.expenseDao.applyLocalCreateServerIdentity(ledger, created.toEntity(ledger).copy(clientRef = clientRef))
            }, RecurringOccurrenceDispatcher({ service }, adapters.recurringOccurrenceAdapter)), now = fixture.clock::millis).drainOnce()
    }

    fun completeFx() {
        fxTask = fxTask.copy(status = "completed")
        network.current = network.current.copy(amountCents = 6000, homeAmountCents = 6000,
            fxRate = "0.05", fxRateDate = "2026-09-11", fxSource = "reference", fxStatus = "ready",
            exchangeRateToCny = "0.05", exchangeRateDate = "2026-09-11", exchangeRateSource = "reference",
            fxTask = fxTask, rowVersion = 2, updatedAt = "2026-09-12T01:00:00Z")
    }

    private fun create(request: ExpenseManualCreateRequestDto): ExpenseDto {
        check(recording)
        return original ?: network.current.copy(status = "pending", source = ExpenseSourceValues.MANUAL_ENTRY,
            amountCents = null, homeAmountCents = null, homeCurrency = "CNY", originalCurrency = "JPY",
            originalCurrencyCode = "JPY", originalAmount = request.originalAmount, originalAmountMinor = 1200,
            merchant = request.merchant, category = requireNotNull(request.category), note = request.note,
            expenseTime = request.spentAt, fxStatus = "pending", fxTask = fxTask, fxRate = null,
            fxRateDate = null, exchangeRateToCny = null, exchangeRateDate = null, rowVersion = 1,
            confirmedAt = null).also { original = it; network.current = it }
    }
    val reads = CopyOnWriteArrayList<Pair<String, String>>()
    val linkCalls = CopyOnWriteArrayList<RecurringOccurrencePaymentRequestDto>()

    fun wrap(delegate: ApiService): ApiService = object : ApiService by delegate {
        override suspend fun createManualExpense(request: ExpenseManualCreateRequestDto): ExpenseDto = create(request)
        override suspend fun expenseFx(id: Long): BackgroundTaskDto = fxTask
        override suspend fun debts(lens: String?) = DebtListResponseDto(emptyList(), homeCurrencyCode = "CNY")
        override suspend fun recurringItems(status: String?, includeArchived: Boolean, month: String?, timezone: String?) =
            RecurringItemListResponseDto(listOf(RecurringItemDto(publicId = "navigation-recurring", ledgerId = "correction-ledger",
                merchant = "日元订阅", merchantKey = "日元订阅", frequency = "monthly", baselineAmountCents = 1200,
                lastAmountCents = 1200, occurrenceCount = 1, lastSeenAt = null, nextExpectedDate = "2026-09-05", status = "active",
                confidence = null, source = "manual", createdAt = "2026-07-01T00:00:00Z", updatedAt = "2026-09-06T00:00:00Z",
                rowVersion = 2, pausedAt = null, archivedAt = null, homeCurrencyCode = recordedCurrency)))

        override suspend fun recurringOccurrence(publicId: String, month: String): RecurringOccurrenceDto {
            check(publicId == "navigation-recurring")
            reads += publicId to month
            val period = if (month == "current") "2026-09" else month
            return RecurringOccurrenceDto(publicId, period, 2, if (fulfilled) 1 else 0,
                if (fulfilled) "fulfilled" else "unfulfilled", 1200, if (fulfilled) 0 else 1200,
                if (fulfilled) "expense-42" else null, if (fulfilled) 1000 else null, "2026-09-05",
                expenseId = if (fulfilled) 42 else null, homeCurrencyCode = recordedCurrency, paidHomeCurrencyCode = "CNY")
        }

        override suspend fun setRecurringOccurrencePayment(
            publicId: String, month: String, request: RecurringOccurrencePaymentRequestDto, idempotencyKey: String,
        ): RecurringOccurrenceDto {
            linkCalls += request
            check(recording && publicId == "navigation-recurring" && month == "2026-08")
            check(request.action == "link" && request.expectedRowVersion == 0L && request.expectedSeriesRowVersion == 2L)
            check(request.expensePublicId == network.current.publicId && request.expectedExpenseRowVersion == network.current.rowVersion)
            check(network.current.status == "confirmed" && idempotencyKey.isNotBlank())
            fulfilled = true
            return recurringOccurrence(publicId, month)
        }
    }.also { service = it }
}
