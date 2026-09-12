package com.ticketbox.data.repository

import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.lifecycle.viewModelScope
import androidx.test.platform.app.InstrumentationRegistry
import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.CurrencyCode
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.viewmodel.ExpenseEditViewModel
import com.ticketbox.viewmodel.PendingViewModel
import com.ticketbox.viewmodel.confirmReadyExpenses
import java.util.concurrent.CopyOnWriteArrayList
import kotlinx.coroutines.awaitCancellation
import kotlinx.coroutines.cancel
import kotlinx.coroutines.runBlocking
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test

/** Real existing editor/repository and disk Room; transport is held before any unseen result can be lost. */
class PendingExpenseAdmissionRoomTest {
    @get:Rule val compose = createComposeRule()
    private var editor: ExpenseEditViewModel? = null
    private var pending: PendingViewModel? = null
    @Volatile private lateinit var current: ExpenseDto
    private var secondPending: ExpenseDto? = null
    @Volatile private var holdTransport = false
    private val requests = CopyOnWriteArrayList<String>()
    private val fixture = ExpenseCorrectionConnectedFixture(InstrumentationRegistry.getInstrumentation().targetContext) { api ->
        object : ApiService by api {
            override suspend fun expense(id: Long): ExpenseDto = current
            override suspend fun pendingExpenses(): List<ExpenseDto> = listOfNotNull(current, secondPending).filter { it.status == "pending" }

            override suspend fun updateExpense(id: String, request: ExpenseUpdateRequest, idempotencyKey: String?): ExpenseDto {
                requests += "patch"
                if (holdTransport) awaitCancellation()
                return current.copy(merchant = request.merchant, rowVersion = current.rowVersion + 1).also { current = it }
            }

            override suspend fun confirmExpense(id: String, request: ExpenseStateTokenRequest, idempotencyKey: String?): ExpenseDto {
                requests += "confirm"
                if (holdTransport) awaitCancellation()
                val original = if (id == current.id.toString()) current else requireNotNull(secondPending)
                check(id == original.id.toString() && request.expectedRowVersion == original.rowVersion)
                return original.copy(status = "confirmed", confirmedAt = "2026-09-06T00:01:00Z",
                    rowVersion = original.rowVersion + 1).also { if (it.id == current.id) current = it else secondPending = it }
            }
        }
    }

    @After fun close() {
        compose.runOnIdle { editor?.viewModelScope?.cancel(); pending?.viewModelScope?.cancel() }
        fixture.close()
    }

    @Test
    fun anOnlineSaveIsDurableBeforeTransportAndKeepsItsOriginalInputAfterRoomReopen() = runBlocking {
        fixture.network.current = fixture.network.current.copy(status = "pending", confirmedAt = null)
        current = fixture.network.current
        val repository = fixture.reopen().expenseRepository
        val original = repository.fetchExpense(42).getOrThrow()
        val result = repository.saveExpenseAllowingOffline(42, draft(), original).getOrThrow()

        val rows = fixture.stored()
        assertEquals("A saved intent must exist before HTTP can start", 1, rows.size)
        assertTrue(result is SaveOutcome.Queued)
        assertTrue("Admission schedules the existing worker; it does not send inline", requests.isEmpty())
        assertEquals("pending", result.expense.status)
        assertEquals(original.rowVersion, result.expense.rowVersion)
        assertPatch(rows.single())
        fixture.reopen()
        assertEquals(rows, fixture.stored())
    }

    @Test
    fun saveAndConfirmKeepBothOriginalCommandsWhenTheEditorStopsBeforeTheFirstResponse() = runBlocking {
        fixture.network.current = fixture.network.current.copy(status = "pending", confirmedAt = null)
        current = fixture.network.current
        val repository = fixture.reopen().expenseRepository
        holdTransport = true
        lateinit var vm: ExpenseEditViewModel
        compose.runOnIdle { vm = ExpenseEditViewModel(42, repository); editor = vm }
        compose.waitUntil(10_000) { !vm.uiState.value.expenseLoading && vm.uiState.value.expense != null }
        assertEquals("pending", vm.uiState.value.expense?.status)
        compose.runOnIdle { vm.confirm(draft()) }
        compose.waitUntil(10_000) { requests.isNotEmpty() || !vm.uiState.value.saving }

        val originals = fixture.stored()
        assertEquals("Both user commands must survive loss of the editor", listOf(
            PendingMutationType.PatchExpense.wireValue, PendingMutationType.ConfirmExpense.wireValue), originals.map { it["type"] })
        assertPatch(originals.first())
        assertEquals(originals.first()["ownerKey"], originals.last()["ownerKey"])
        assertEquals(originals.first()["ledgerId"], originals.last()["ledgerId"])
        assertEquals(originals.first()["serverUrl"], originals.last()["serverUrl"])
        assertEquals(listOf("expense:42", "expense:42"), originals.map { it["targetId"] })
        assertEquals(listOf("7", "7"), originals.map { it["expectedRowVersion"] })
        assertEquals(2, originals.map { it["idempotencyKey"] }.filterNotNull().filter { it.isNotBlank() }.distinct().size)
        assertTrue("Worker transport follows durable admission", requests.isEmpty())
        assertEquals("pending", vm.uiState.value.expense?.status)
        assertNotNull(vm.uiState.value.message)
        compose.runOnIdle { vm.viewModelScope.cancel(); editor = null }
        fixture.reopen()
        assertEquals(originals, fixture.stored())
    }

    @Test
    fun readyBatchPreservesBothConfirmIntentsBeforeTransportAndAfterLeavingTheInbox() = runBlocking {
        fixture.network.current = fixture.network.current.copy(status = "pending", confirmedAt = null)
        current = fixture.network.current
        secondPending = current.copy(id = 43, publicId = "expense-43")
        val repository = fixture.reopen().expenseRepository
        lateinit var vm: PendingViewModel
        compose.runOnIdle { vm = PendingViewModel(repository, fixture.uploadIntents); pending = vm }
        compose.waitUntil(10_000) { vm.uiState.value.items.size == 2 && !vm.uiState.value.readOnly }
        compose.runOnIdle { vm.confirmReadyExpenses() }
        compose.waitUntil(10_000) { vm.uiState.value.bulkConfirm.total == 2 && !vm.uiState.value.bulkConfirm.running }

        val originals = fixture.stored()
        assertEquals("Both reviewed bills need durable original commands", 2, originals.size)
        assertEquals(listOf("expense:42", "expense:43"), originals.map { it["targetId"] })
        assertTrue(originals.all { it["type"] == PendingMutationType.ConfirmExpense.wireValue })
        assertTrue(originals.all { it["status"] == PendingMutationStatus.Pending.wireValue })
        assertEquals(listOf("7", "7"), originals.map { it["expectedRowVersion"] })
        assertEquals(2, originals.mapNotNull { it["idempotencyKey"]?.takeIf(String::isNotBlank) }.distinct().size)
        assertTrue("The existing worker sends after admission", requests.isEmpty())
        assertEquals("pending", current.status)
        assertNotNull(vm.uiState.value.message)
        compose.runOnIdle { vm.viewModelScope.cancel(); pending = null }
        fixture.reopen()
        assertEquals(originals, fixture.stored())
    }

    private fun assertPatch(row: Map<String, String?>) {
        assertEquals(PendingMutationType.PatchExpense.wireValue, row["type"])
        assertEquals(PendingMutationStatus.Pending.wireValue, row["status"])
        assertEquals("expense:42", row["targetId"])
        assertEquals("7", row["expectedRowVersion"])
        assertTrue(!row["idempotencyKey"].isNullOrBlank())
        val patch = requireNotNull(OutboxAdapterGraph().patchExpenseAdapter.fromJson(requireNotNull(row["payload"])))
        assertEquals("自己输入的商家", patch.merchant)
        assertEquals("未丢的草稿", patch.note)
        assertEquals("12.34", patch.originalAmount)
        assertEquals(null, patch.originalCurrency)
        assertEquals("2026-09-06T00:00:00Z", patch.spentAt)
        assertEquals(null, patch.expectedRowVersion)
    }

    private fun draft() = ExpenseDraft(amountCents = 1234, ledgerHomeCurrency = CurrencyCode.CNY,
        originalCurrencyCode = CurrencyCode.CNY, originalAmountMinor = 1234, merchant = "自己输入的商家",
        category = "餐饮", note = "未丢的草稿", expenseTime = "2026-09-06T00:00:00Z",
        tags = null, valueScore = null, regretScore = null)
}
