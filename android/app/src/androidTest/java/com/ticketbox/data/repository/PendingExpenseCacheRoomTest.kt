package com.ticketbox.data.repository

import android.content.Context
import androidx.test.core.app.ApplicationProvider
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.BackgroundTaskDto
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.screens.expense.expenseFxTaskStatusRes
import java.io.IOException
import kotlinx.coroutines.CompletableDeferred
import kotlinx.coroutines.async
import kotlinx.coroutines.runBlocking
import kotlinx.coroutines.withTimeout
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Real repositories, disk Room and drain; only server responses are controlled. */
class PendingExpenseCacheRoomTest {
    private lateinit var current: ExpenseDto
    private lateinit var sendingApi: ApiService
    private var offline = false
    private var pendingResponse: (suspend () -> List<ExpenseDto>)? = null
    private val fixture = ExpenseCorrectionConnectedFixture(ApplicationProvider.getApplicationContext<Context>()) { api ->
        object : ApiService by api {
            override suspend fun expense(id: Long): ExpenseDto {
                if (offline) throw IOException("Offline detail")
                return current.copy(id = id, publicId = "expense-$id")
            }
            override suspend fun pendingExpenses(): List<ExpenseDto> = pendingResponse?.invoke()
                ?: listOf(current).filter { it.status == "pending" }
            override suspend fun updateExpense(id: String, request: ExpenseUpdateRequest, idempotencyKey: String?): ExpenseDto {
                check(id == current.id.toString() && request.expectedRowVersion == current.rowVersion)
                check(!idempotencyKey.isNullOrBlank())
                return current.copy(merchant = request.merchant, rowVersion = current.rowVersion + 1).also { current = it }
            }
            override suspend fun rejectExpense(id: String, request: ExpenseStateTokenRequest, idempotencyKey: String?): ExpenseDto {
                if (offline) throw IOException("Offline rejection")
                check(id == current.id.toString() && request.expectedRowVersion == current.rowVersion)
                check(!idempotencyKey.isNullOrBlank())
                return current.copy(status = "rejected", rowVersion = current.rowVersion + 1).also { current = it }
            }
            override suspend fun undoExpense(id: Long, request: ExpenseStateTokenRequest): ExpenseDto {
                check(id == current.id && request.expectedRowVersion == current.rowVersion)
                return current.copy(status = "pending", rowVersion = current.rowVersion + 1).also { current = it }
            }
        }.also { sendingApi = it }
    }

    @After fun close() { fixture.close() }

    @Test fun livePendingReadRetainsFxTaskForTheMatchingRevisionWithoutInventingOfflineTaskState() = runBlocking {
        val repository = start()
        val statuses = listOf("queued" to R.string.expense_fx_queued, "running" to R.string.expense_fx_running,
            "failed" to R.string.expense_fx_failed, "cancelled" to R.string.expense_fx_failed)
        for ((status, expectedLabel) in statuses) {
            current = current.copy(amountCents = null, originalCurrencyCode = "USD", originalAmountMinor = 1000,
                fxStatus = "pending", fxTask = fxTask(status))
            val observed = repository.syncPending().getOrThrow().single()
            assertEquals(current.fxTask?.toDomain(), observed.fxTask)
            assertEquals(expectedLabel, expenseFxTaskStatusRes(observed.fxTask))
            assertEquals(current.rowVersion, observed.rowVersion)
        }
        offline = true
        val cached = fixture.reopen().expenseRepository.getCachedPending().getOrThrow().single()
        assertEquals(current.rowVersion, cached.rowVersion)
        assertEquals("pending", cached.fxStatus)
        assertEquals(null, cached.fxTask)
        assertEquals(R.string.expense_fx_waiting, expenseFxTaskStatusRes(cached.fxTask))
    }

    @Test fun acceptedPendingPatchReopensItsSavedFieldsAndTokenWhileOffline() = runBlocking {
        val repository = start()
        val original = repository.fetchExpense(42).getOrThrow()
        val accepted = repository.updateExpense(42, draft(), original).getOrThrow()
        assertEquals("Saved merchant", accepted.merchant)
        assertEquals(2L, accepted.rowVersion)
        offline = true

        val reopened = fixture.reopen().expenseRepository
        assertTrue(reopened.fetchExpense(42).isFailure)
        val cached = reopened.fetchExpenseFromLocalCache(42).getOrThrow()
        assertEquals(accepted.merchant, cached.merchant)
        assertEquals(accepted.rowVersion, cached.rowVersion)
        assertEquals("pending", cached.status)
        assertEquals(cached, reopened.getCachedPending().getOrThrow().single())
        assertTrue(fixture.stored().isEmpty())
        assertEquals(0, fixture.confirmedCallbacks)
    }

    @Test fun rejectionSurvivesAnOlderListAndReopenUntilAnExplicitUndoReturnsPending() = runBlocking {
        val repository = start()
        repository.fetchExpense(42).getOrThrow()
        val before = current
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        pendingResponse = { started.complete(Unit); release.await(); listOf(before) }
        val staleRead = async { repository.syncPending().getOrThrow() }
        withTimeout(5_000) { started.await() }
        try { repository.rejectExpense(42, 1).getOrThrow() } finally { release.complete(Unit) }
        assertTrue(withTimeout(5_000) { staleRead.await() }.isEmpty())
        offline = true
        val reopened = fixture.reopen().expenseRepository
        assertTrue(reopened.getCachedPending().getOrThrow().isEmpty())
        assertTrue(reopened.fetchExpenseFromLocalCache(42).isFailure)

        offline = false
        val restored = reopened.undoRejectExpense(42, 2).getOrThrow()
        assertEquals(3L, restored.rowVersion)
        assertEquals(restored, reopened.fetchExpenseFromLocalCache(42).getOrThrow())
        assertEquals(restored, reopened.getCachedPending().getOrThrow().single())
    }

    @Test fun acceptedOutboxRejectionCannotReappearAsPendingAfterRoomReopen() = runBlocking {
        val repository = start()
        val pending = repository.fetchExpense(42).getOrThrow()
        offline = true
        assertTrue(repository.rejectExpenseAllowingOffline(pending).getOrThrow() is ExpenseStateOutcome.Queued)
        val original = fixture.pendingDao.allRows().single()
        offline = false
        val dispatcher = RejectExpenseDispatcher(apiProvider = { sendingApi },
            payloadAdapter = OutboxAdapterGraph().expenseStateTokenAdapter,
            publishExpense = { ledgerId, expense -> fixture.expenseDao.applyServerExpense(ledgerId, expense.toEntity(ledgerId)); Unit })
        assertEquals(1, OutboxDrainEngine(fixture.outbox, listOf(dispatcher), now = fixture.clock::millis).drainOnce().done)
        val delivered = fixture.pendingDao.allRows().single()
        assertEquals(PendingMutationStatus.Done.wireValue, delivered.status)
        assertEquals(original.idempotencyKey, delivered.idempotencyKey)
        assertEquals(original.payload, delivered.payload)
        offline = true

        val reopened = fixture.reopen().expenseRepository
        assertTrue(reopened.getCachedPending().getOrThrow().isEmpty())
        assertTrue(reopened.fetchExpenseFromLocalCache(42).isFailure)
    }

    @Test fun delayedPendingListCannotEraseNewerDetailOrANewlyObservedBillInTheSameLedger() = runBlocking {
        val repository = start()
        current = current.copy(fxTask = fxTask("failed"))
        repository.fetchExpense(42).getOrThrow()
        fixture.expenseDao.insert(current.copy(id = 45, publicId = "stale-45").toEntity("correction-ledger"))
        fixture.expenseDao.insert(current.copy(publicId = "other-ledger-expense-42").toEntity("other-ledger"))
        val before = current
        val started = CompletableDeferred<Unit>()
        val release = CompletableDeferred<Unit>()
        pendingResponse = { started.complete(Unit); release.await(); listOf(before) }
        val staleRead = async { repository.syncPending().getOrThrow() }
        withTimeout(5_000) { started.await() }
        try {
            current = current.copy(merchant = "Fresh review", rowVersion = 2)
            repository.fetchExpense(42).getOrThrow()
            repository.fetchExpense(43).getOrThrow()
        } finally { release.complete(Unit) }

        val observed = withTimeout(5_000) { staleRead.await() }.associateBy { it.id }
        assertEquals(setOf(42L, 43L), observed.keys)
        assertEquals(2L, observed.getValue(42).rowVersion)
        assertEquals("Fresh review", observed.getValue(42).merchant)
        assertEquals(null, observed.getValue(42).fxTask)
        assertEquals(null, observed.getValue(43).fxTask)
        assertEquals(observed, repository.getCachedPending().getOrThrow().associateBy { it.id })
        assertEquals(1L, fixture.expenseDao.getPending("other-ledger").single().rowVersion)
    }

    private fun start(): ExpenseRepository {
        val repository = fixture.reopen().expenseRepository
        current = fixture.network.current.copy(status = "pending", confirmedAt = null, rowVersion = 1)
        return repository
    }

    private fun fxTask(status: String) = BackgroundTaskDto(publicId = "fx-42", taskType = "expense_fx", status = status,
        sourceExpenseId = 42, createdAt = "2026-09-06T00:00:00Z")

    private fun draft() = ExpenseDraft(amountCents = 1000, originalCurrencyCode = CurrencyCode.CNY,
        originalAmountMinor = 1000, ledgerHomeCurrency = CurrencyCode.CNY, merchant = "Saved merchant",
        category = "Other", note = null, expenseTime = "2026-09-06T00:00:00Z", tags = null,
        valueScore = null, regretScore = null)
}
