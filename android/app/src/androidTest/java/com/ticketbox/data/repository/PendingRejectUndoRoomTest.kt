package com.ticketbox.data.repository

import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.test.assertHasClickAction
import androidx.compose.ui.test.assertIsDisplayed
import androidx.compose.ui.test.assertIsEnabled
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.R
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.ui.screens.pending.PendingUndoRejectBanner
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.PendingViewModel
import java.io.IOException
import java.time.Instant
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real Pending VM, disk Room, dispatcher and banner; only remote transport is synthetic. */
class PendingRejectUndoRoomTest {
    @get:Rule val compose = createComposeRule()
    private val context = InstrumentationRegistry.getInstrumentation().targetContext
    private var pending: PendingViewModel? = null
    @Volatile private lateinit var current: ExpenseDto
    @Volatile private var acceptReject = false
    private lateinit var sendingApi: ApiService
    private val attempts = CopyOnWriteArrayList<Pair<ExpenseStateTokenRequest, String>>()
    private val fixture = ExpenseCorrectionConnectedFixture(context) { api ->
        object : ApiService by api {
            override suspend fun expense(id: Long): ExpenseDto {
                check(id == current.id)
                if (current.status == "rejected") throw IOException("Canonical read unavailable after acceptance")
                return current
            }

            override suspend fun pendingExpenses(): List<ExpenseDto> = listOf(current).filter { it.status == "pending" }

            override suspend fun rejectExpense(id: String, request: ExpenseStateTokenRequest, idempotencyKey: String?): ExpenseDto {
                check(id == current.id.toString() && !idempotencyKey.isNullOrBlank())
                attempts += request to idempotencyKey
                if (!acceptReject) throw IOException("Rejection transport unavailable before acceptance")
                check(current.status == "pending" && request.expectedRowVersion == current.rowVersion)
                val acceptedAt = Instant.now().toString()
                return current.copy(status = "rejected", rowVersion = current.rowVersion + 1,
                    rejectedAt = acceptedAt, updatedAt = acceptedAt).also { current = it }
            }
        }.also { sendingApi = it }
    }

    @After fun close() {
        compose.runOnIdle { pending?.viewModelScope?.cancel() }
        fixture.close()
    }

    @Test
    fun aQueuedRejectionOffersUndoFromItsOriginalRoomReceiptAfterTheWorkerAcceptsIt() = runBlocking {
        current = fixture.network.current.copy(status = "pending", confirmedAt = null, rejectedAt = null)
        val repository = fixture.reopen().expenseRepository
        lateinit var vm: PendingViewModel
        compose.runOnIdle { vm = PendingViewModel(repository, fixture.uploadIntents); pending = vm }
        compose.setContent { TicketboxTheme {
            val state by vm.uiState.collectAsState()
            state.undoableExpense?.let { PendingUndoRejectBanner(expense = it, onUndo = vm::undoReject) }
        } }
        compose.waitUntil(10_000) { vm.uiState.value.items.size == 1 && !vm.uiState.value.readOnly }
        val reviewed = vm.uiState.value.items.single()
        compose.runOnIdle { vm.reject(reviewed) }
        compose.waitUntil(10_000) { vm.uiState.value.message != null && vm.uiState.value.actionInProgressIds.isEmpty() }

        val original = fixture.pendingDao.allRows().single()
        assertEquals(PendingMutationType.RejectExpense.wireValue, original.type)
        assertEquals(PendingMutationStatus.Pending.wireValue, original.status)
        assertEquals(reviewed.rowVersion, original.expectedRowVersion)
        assertFalse(original.idempotencyKey.isNullOrBlank())
        assertEquals("pending", current.status)
        assertNull("Queued rejection is not an accepted server rejection", vm.uiState.value.undoableExpense)

        acceptReject = true
        val dispatcher = RejectExpenseDispatcher(apiProvider = { sendingApi },
            payloadAdapter = OutboxAdapterGraph().expenseStateTokenAdapter,
            publishExpense = { ledgerId, expense -> fixture.expenseDao.applyServerExpense(ledgerId, expense.toEntity(ledgerId)); Unit })
        val engine = OutboxDrainEngine(fixture.outbox, listOf(dispatcher), now = fixture.clock::millis)
        assertEquals(1, engine.drainOnce().done)
        val delivered = fixture.pendingDao.allRows().single()
        assertEquals(PendingMutationStatus.Done.wireValue, delivered.status)
        assertEquals(original.idempotencyKey, delivered.idempotencyKey)
        assertEquals(original.payload, delivered.payload)
        assertEquals(original.expectedRowVersion, delivered.expectedRowVersion)
        assertEquals(original.ownerKey, delivered.ownerKey)
        assertEquals(original.ledgerId, delivered.ledgerId)
        assertEquals(original.serverUrl, delivered.serverUrl)
        assertEquals(original.targetId, delivered.targetId)
        assertTrue(attempts.all { it.first.expectedRowVersion == reviewed.rowVersion && it.second == original.idempotencyKey })
        assertTrue(repository.getCachedPending().getOrThrow().isEmpty())
        assertNotNull("Accepted rejection must retain its original receipt with Done", delivered.receiptJson)
        assertEquals(current.id, expenseAcceptanceReceiptId(delivered.receiptJson))

        compose.waitUntil(5_000) { vm.uiState.value.undoableExpense != null }
        val undoable = requireNotNull(vm.uiState.value.undoableExpense)
        assertEquals(current.id, undoable.id)
        assertEquals(current.rowVersion, undoable.rowVersion)
        assertEquals(current.rejectedAt, undoable.rejectedAt)
        assertEquals(reviewed.merchant, undoable.merchant)
        compose.onNodeWithText(context.getString(R.string.pending_undo_banner_action))
            .assertIsDisplayed().assertIsEnabled().assertHasClickAction()
        val attemptsAfterAcceptance = attempts.size
        assertEquals(0, engine.drainOnce().done)
        assertEquals(attemptsAfterAcceptance, attempts.size)

        compose.runOnIdle { vm.viewModelScope.cancel(); pending = null }
        val retained = fixture.stored()
        fixture.reopen()
        assertEquals(retained, fixture.stored())
    }
}
