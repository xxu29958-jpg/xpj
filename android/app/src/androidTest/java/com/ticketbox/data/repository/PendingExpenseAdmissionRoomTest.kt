package com.ticketbox.data.repository

import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.test.hasSetTextAction
import androidx.compose.ui.test.hasText
import androidx.compose.ui.test.junit4.v2.createComposeRule
import androidx.compose.ui.test.onNodeWithText
import androidx.compose.ui.test.performClick
import androidx.compose.ui.test.performTextInput
import androidx.lifecycle.viewModelScope
import androidx.lifecycle.SavedStateHandle
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
import com.ticketbox.domain.model.AppSkin
import com.ticketbox.ui.asString
import com.ticketbox.ui.saveConsumerArtPreview
import com.ticketbox.ui.screens.pending.PendingReviewSheetHost
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostState
import com.ticketbox.ui.screens.pending.PendingReviewSheetHostActions
import com.ticketbox.ui.theme.TicketboxTheme
import com.ticketbox.viewmodel.ExpenseEditViewModel
import com.ticketbox.viewmodel.PendingViewModel
import com.ticketbox.viewmodel.confirmReadyExpenses
import com.ticketbox.viewmodel.openQuickCategory
import com.ticketbox.viewmodel.saveQuickCategory
import com.ticketbox.viewmodel.closeSheet
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
    private lateinit var admissionApi: ApiService
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
                    rowVersion = original.rowVersion + 1).withConfirmationReceipt()
                    .also { if (it.id == current.id) current = it else secondPending = it }
            }
        }.also { admissionApi = it }
    }

    @After fun close() {
        compose.runOnIdle { editor?.viewModelScope?.cancel(); pending?.viewModelScope?.cancel() }
        fixture.close()
    }

    @Test
    fun quickCategoryKeepsTheOpenedVersionAndSelectedValueInRoomAfterAPeerRefresh() = runBlocking {
        current = fixture.network.current.copy(status = "pending", confirmedAt = null, category = "")
        val repository = fixture.reopen().expenseRepository
        lateinit var vm: PendingViewModel
        compose.runOnIdle { vm = PendingViewModel(repository, fixture.uploadIntents, expenseReader = repository); pending = vm }
        compose.waitUntil(10_000) { vm.uiState.value.items.size == 1 && !vm.uiState.value.readOnly }
        val original = vm.uiState.value.items.single()
        showQuickCategory(vm)
        compose.runOnIdle { vm.openQuickCategory(original) }
        compose.waitForIdle()
        saveConsumerArtPreview("quick-category-context", InstrumentationRegistry.getInstrumentation().uiAutomation.takeScreenshot())
        compose.onNode(hasSetTextAction()).performTextInput("购物")
        current = current.copy(category = "医疗", rowVersion = current.rowVersion + 1)
        compose.runOnIdle { vm.refresh() }
        compose.waitUntil(10_000) { vm.uiState.value.items.single().rowVersion == current.rowVersion }
        compose.onNode(hasSetTextAction() and hasText("购物")).assertExists()
        androidx.test.espresso.Espresso.closeSoftKeyboard()
        compose.waitForIdle()
        val instrumentation = InstrumentationRegistry.getInstrumentation()
        instrumentation.uiAutomation.waitForIdle(250, 5_000)
        saveConsumerArtPreview("quick-category-original-basis", instrumentation.uiAutomation.takeScreenshot())
        compose.onNodeWithText("保存分类").performClick()
        compose.waitUntil(10_000) { fixture.stored().size == 1 }

        val originals = fixture.stored()
        val row = originals.single()
        assertEquals(original.rowVersion.toString(), row["expectedRowVersion"])
        val payload = requireNotNull(OutboxAdapterGraph().patchExpenseAdapter.fromJson(requireNotNull(row["payload"])))
        assertEquals("购物", payload.category)
        assertEquals(null, payload.originalAmount)
        assertEquals("医疗", current.category)
        assertEquals(original.rowVersion + 1, current.rowVersion)
        assertEquals(original.amountCents, current.amountCents)
        assertEquals("pending", current.status)
        assertTrue("Only the existing worker may deliver this original intent", requests.isEmpty())
        compose.runOnIdle { vm.viewModelScope.cancel(); pending = null }
        fixture.reopen()
        assertEquals(originals, fixture.stored())
    }

    private fun showQuickCategory(vm: PendingViewModel) {
        compose.setContent { TicketboxTheme(skin = if (InstrumentationRegistry.getArguments().getString("captureSkin") == "midnight")
            AppSkin.Midnight else AppSkin.Paper) {
            val state by vm.uiState.collectAsState()
            PendingReviewSheetHost(
                state = PendingReviewSheetHostState(state.activeSheet, state.categoryOptions,
                    state.actionInProgressIds, 0, 0, 0, false, 0, 0, state.reviewRemaining, state.message?.asString()),
                actions = PendingReviewSheetHostActions(
                    onSaveQuickCategory = vm::saveQuickCategory, onSaveQuickMerchant = { _, _ -> },
                    onSaveAmountDraft = { _, _ -> }, onSaveAmountAndConfirm = { _, _ -> },
                    onSkipReviewField = {}, onKeepBoth = {}, onIgnoreCurrent = {},
                    onConfirmReady = {}, onDismiss = vm::closeSheet),
            )
        } }
    }

    @Test
    fun anOnlineSaveIsDurableBeforeTransportAndKeepsItsOriginalInputAfterRoomReopen() = runBlocking {
        fixture.network.current = fixture.network.current.copy(status = "pending", confirmedAt = null)
        current = fixture.network.current
        val repository = fixture.reopen().expenseRepository
        val original = repository.fetchExpense(42).getOrThrow()
        val result = repository.saveExpenseAllowingOffline(requireNotNull(repository.captureDeferredLedgerBinding()), 42, draft(), original).getOrThrow()

        val rows = fixture.stored()
        assertEquals("A saved intent must exist before HTTP can start", 1, rows.size)
        assertEquals(rows.map { it["id"]?.toLong() }, result.rowIds)
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
    fun anOldEditorCannotSendOrAdmitItsDraftAfterTheLedgerBindingChanges() = runBlocking {
        fixture.network.current = fixture.network.current.copy(status = "pending", confirmedAt = null)
        current = fixture.network.current
        val repository = fixture.reopen().expenseRepository
        lateinit var vm: ExpenseEditViewModel
        compose.runOnIdle { vm = ExpenseEditViewModel(42, repository); editor = vm }
        compose.waitUntil(10_000) { !vm.uiState.value.expenseLoading && vm.uiState.value.expense != null }
        val original = requireNotNull(vm.uiState.value.expense)
        fixture.switchLedger()

        compose.runOnIdle { vm.save(draft()) }
        compose.waitUntil(10_000) { !vm.uiState.value.saving && vm.uiState.value.message != null }

        assertTrue("The old editor must not send to the later binding", requests.isEmpty())
        assertTrue("No old draft may enter the later ledger queue", fixture.stored().isEmpty())
        assertEquals(original, vm.uiState.value.expense)
        assertEquals(false, vm.uiState.value.done)
        assertEquals(original.merchant, current.merchant)
        assertEquals(original.rowVersion, current.rowVersion)
    }

    @Test
    fun readyBatchPreservesBothConfirmIntentsBeforeTransportAndAfterLeavingTheInbox() = runBlocking {
        fixture.network.current = fixture.network.current.copy(status = "pending", confirmedAt = null)
        current = fixture.network.current
        secondPending = current.copy(id = 43, publicId = "expense-43")
        val repository = fixture.reopen().expenseRepository
        lateinit var vm: PendingViewModel
        compose.runOnIdle { vm = PendingViewModel(repository, fixture.uploadIntents, expenseReader = repository); pending = vm }
        compose.waitUntil(10_000) { vm.uiState.value.items.size == 2 && !vm.uiState.value.readOnly }
        compose.runOnIdle { vm.confirmReadyExpenses() }
        compose.waitUntil(10_000) { vm.uiState.value.bulkConfirm.total == 2 && !vm.uiState.value.bulkConfirm.running }

        val originals = fixture.stored()
        assertEquals("Both reviewed bills need durable original commands", 2, originals.size)
        assertEquals(2, originals.size)
        assertEquals(setOf("expense:42", "expense:43"), originals.map { it["targetId"] }.toSet())
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

    @Test
    fun selectedOriginalCommandsRestoreTheirFirstReceiptAcrossRoomReopen() = runBlocking {
        current = fixture.network.current.copy(status = "pending", confirmedAt = null)
        val saved = SavedStateHandle()
        var repository = fixture.reopen().expenseRepository
        compose.runOnIdle { editor = ExpenseEditViewModel(42, repository, savedState = saved) }
        compose.waitUntil(10_000) { editor?.uiState?.value?.expenseLoading == false }
        compose.runOnIdle { editor!!.confirm(draft()) }
        compose.waitUntil(10_000) { editor!!.uiState.value.commandRowIds.size == 2 }
        val originalIds = editor!!.uiState.value.commandRowIds
        val restored = SavedStateHandle(saved.keys().associateWith { saved.get<Any>(it) })
        compose.runOnIdle { editor!!.viewModelScope.cancel() }
        repository = fixture.reopen().expenseRepository
        compose.runOnIdle { editor = ExpenseEditViewModel(42, repository, savedState = restored) }
        compose.waitUntil(10_000) { editor?.uiState?.value?.expenseLoading == false }
        assertEquals(originalIds, editor!!.uiState.value.commandRowIds)
        assertEquals(false, editor!!.uiState.value.done)
        val adapters = OutboxAdapterGraph()
        OutboxDrainEngine(fixture.outbox, listOf(
            PatchExpenseDispatcher({ admissionApi }, adapters.patchExpenseAdapter, fixture::publishExpense),
            ConfirmExpenseDispatcher({ admissionApi }, adapters.expenseStateTokenAdapter, fixture::publishExpense),
        ), now = fixture.clock::millis).drainOnce()
        compose.waitUntil(10_000) { editor!!.uiState.value.confirmationReceipt != null }
        val firstReceipt = editor!!.uiState.value.confirmationReceipt
        assertEquals("自己输入的商家", firstReceipt?.merchant)
        compose.runOnIdle { editor!!.viewModelScope.cancel() }
        current = current.copy(merchant = "后来人工更正", rowVersion = current.rowVersion + 1, confirmationReceipt = null)
        repository = fixture.reopen().expenseRepository
        compose.runOnIdle { editor = ExpenseEditViewModel(42, repository, savedState = restored) }
        compose.waitUntil(10_000) { editor!!.uiState.value.confirmationReceipt != null && !editor!!.uiState.value.expenseLoading }
        assertEquals(firstReceipt, editor!!.uiState.value.confirmationReceipt)
        assertEquals("后来人工更正", editor!!.uiState.value.expense?.merchant)
        fixture.switchLedger()
        compose.waitUntil(10_000) { editor!!.uiState.value.confirmationReceipt == null }
        assertEquals(originalIds, editor!!.uiState.value.commandRowIds)
        assertEquals(false, editor!!.uiState.value.done)
    }

    private fun draft() = ExpenseDraft(amountCents = 1234, ledgerHomeCurrency = CurrencyCode.CNY,
        originalCurrencyCode = CurrencyCode.CNY, originalAmountMinor = 1234, merchant = "自己输入的商家",
        category = "餐饮", note = "未丢的草稿", expenseTime = "2026-09-06T00:00:00Z",
        tags = null, valueScore = null, regretScore = null)
}
