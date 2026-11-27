package com.ticketbox.data.repository

import com.ticketbox.OutboxAdapterGraph
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.dto.ExpenseUpdateRequest
import com.ticketbox.domain.model.Expense
import com.ticketbox.domain.model.ExpenseDraft
import com.ticketbox.ui.screens.expense.ExpenseEditFormValues
import com.ticketbox.viewmodel.ExpenseFactInputCodec
import com.ticketbox.viewmodel.ExpenseFactInputDraft
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * Pins the shared request-building boundary between PATCH diff semantics
 * ([toPatchPayload]) and ConfirmExpense atomic-change semantics
 * ([toConfirmationChanges]) across unmodified, explicit-clear (`""`), and
 * explicit-set values through Outbox persistence and dispatcher replay.
 */
internal class ExpenseUpdateRequestSemanticsTest : ExpensePendingRepositoryOutboxTestBase() {
    private val wireGraph = OutboxAdapterGraph()

    private suspend fun enqueueAndReplayPatch(
        baseline: Expense,
        patchDraft: ExpenseDraft,
    ): Pair<String, ExpenseUpdateRequest> {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val stub = ApiServiceStub(updateExpenseResult = ApiResult.Success(successExpenseDto()))
        val repo = buildRepository(
            api = stub,
            outbox = outbox,
            adapter = wireGraph.patchExpenseAdapter,
            stateTokenAdapter = wireGraph.expenseStateTokenAdapter,
        )
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val accepted = repo.saveExpenseAllowingOffline(binding, baseline.id, patchDraft, baseline).getOrThrow()
        val row = dao.rows.getValue(accepted.rowIds.single()).toDomain()
        val result = PatchExpenseDispatcher(
            apiProvider = { stub },
            payloadAdapter = wireGraph.patchExpenseAdapter,
            publishExpense = { _, _ -> },
        ).dispatch(row)
        assertTrue(result is DispatchResult.Success, "expected patch replay success, got $result")
        return row.payloadJson to requireNotNull(stub.lastUpdateRequest)
    }

    private suspend fun enqueueAndReplayConfirm(
        baseline: Expense,
        confirmDraft: ExpenseDraft,
    ): Triple<OutboxRow, ExpenseStateTokenRequest, String> {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        var captured: ExpenseStateTokenRequest? = null
        val stub = ApiServiceStub(confirmExpenseResult = ApiResult.Success(confirmationResponse()))
        val api = object : ApiService by stub {
            override suspend fun confirmExpense(
                id: String,
                request: ExpenseStateTokenRequest,
                idempotencyKey: String?,
            ): ExpenseDto {
                captured = request
                return stub.confirmExpense(id, request, idempotencyKey)
            }
        }
        val repo = buildRepository(
            api = api,
            outbox = outbox,
            adapter = wireGraph.patchExpenseAdapter,
            stateTokenAdapter = wireGraph.expenseStateTokenAdapter,
        )
        val binding = requireNotNull(repo.captureDeferredLedgerBinding())
        val accepted = repo.saveAndConfirmExpense(binding, baseline, confirmDraft).getOrThrow()
        val row = dao.rows.getValue(accepted.rowIds.single()).toDomain()
        val result = ConfirmExpenseDispatcher(
            apiProvider = { api },
            payloadAdapter = wireGraph.expenseStateTokenAdapter,
            publishExpense = { _, _ -> },
        ).dispatch(row)
        assertTrue(result is DispatchResult.Success, "expected confirm replay success, got $result")
        val dispatched = requireNotNull(captured)
        return Triple(row, dispatched, wireGraph.expenseStateTokenAdapter.toJson(dispatched))
    }

    @Test
    fun `patch preserves exclude_unset for unmodified merchant and serializes clear and set through replay`() = runTest {
        val baseline = baselineExpense()

        val (unchangedPayload, unchangedDispatched) = enqueueAndReplayPatch(
            baseline = baseline,
            patchDraft = draft.copy(merchant = "原商家", note = "仅改备注"),
        )
        assertFalse(unchangedPayload.contains("\"merchant\""), "unchanged PATCH must omit merchant: $unchangedPayload")
        assertNull(unchangedDispatched.merchant)
        assertFalse(wireGraph.patchExpenseAdapter.toJson(unchangedDispatched).contains("\"merchant\""))

        val (clearedPayload, clearedDispatched) = enqueueAndReplayPatch(
            baseline = baseline,
            patchDraft = draft.copy(merchant = ""),
        )
        assertTrue(clearedPayload.contains("\"merchant\":\"\""), "clear PATCH must persist empty string: $clearedPayload")
        assertEquals("", clearedDispatched.merchant)
        assertTrue(wireGraph.patchExpenseAdapter.toJson(clearedDispatched).contains("\"merchant\":\"\""))

        val (updatedPayload, updatedDispatched) = enqueueAndReplayPatch(
            baseline = baseline,
            patchDraft = draft.copy(merchant = "新商家"),
        )
        assertTrue(updatedPayload.contains("\"merchant\":\"新商家\""), "set PATCH must persist value: $updatedPayload")
        assertEquals("新商家", updatedDispatched.merchant)
        assertTrue(wireGraph.patchExpenseAdapter.toJson(updatedDispatched).contains("\"merchant\":\"新商家\""))
    }

    @Test
    fun `confirm retains reviewed non-blank merchant and preserves clear, set, and untouched blank through replay`() = runTest {
        val baseline = baselineExpense()

        val (unchangedRow, unchangedReq, unchangedWire) = enqueueAndReplayConfirm(
            baseline = baseline,
            confirmDraft = draft.copy(merchant = "原商家"),
        )
        assertEquals("原商家", unchangedRow.confirmationChanges()?.merchant)
        assertEquals("原商家", unchangedReq.changes?.merchant)
        assertTrue(unchangedWire.contains("\"merchant\":\"原商家\""), "confirm must keep reviewed merchant: $unchangedWire")

        val (clearedRow, clearedReq, clearedWire) = enqueueAndReplayConfirm(
            baseline = baseline,
            confirmDraft = draft.copy(merchant = ""),
        )
        assertEquals("", clearedRow.confirmationChanges()?.merchant)
        assertEquals("", clearedReq.changes?.merchant)
        assertTrue(clearedWire.contains("\"merchant\":\"\""), "confirm clear must send empty string: $clearedWire")

        val (updatedRow, updatedReq, updatedWire) = enqueueAndReplayConfirm(
            baseline = baseline,
            confirmDraft = draft.copy(merchant = "新商家"),
        )
        assertEquals("新商家", updatedRow.confirmationChanges()?.merchant)
        assertEquals("新商家", updatedReq.changes?.merchant)
        assertTrue(updatedWire.contains("\"merchant\":\"新商家\""), "confirm set must send new merchant: $updatedWire")

        val blankBaseline = baseline.copy(merchant = null)
        val (blankRow, blankReq, blankWire) = enqueueAndReplayConfirm(
            baseline = blankBaseline,
            confirmDraft = draft.copy(merchant = ""),
        )
        assertNull(blankRow.confirmationChanges()?.merchant)
        assertNull(blankReq.changes?.merchant)
        assertFalse(blankWire.contains("\"merchant\""), "confirm untouched blank must stay omitted: $blankWire")
    }

    @Test
    fun `pending funding retained edits preserve unmodified, explicit clear, explicit set, and amount clear`() {
        val baseline = baselineExpense()

        val unchangedEncoded = ExpenseFactInputCodec.encode(
            ExpenseFactInputDraft(
                baseline = baseline,
                fundingJson = "[]",
                confirmationChanges = draft.copy(merchant = "原商家", note = "补备注").toPatchPayload(baseline),
            ),
        )
        val unchangedDecoded = ExpenseFactInputCodec.decode(unchangedEncoded, baseline.id).confirmationChanges
        assertNull(unchangedDecoded?.merchant)
        assertEquals("原商家", ExpenseEditFormValues.fromConfirmation(baseline, unchangedDecoded).merchant)
        assertEquals(
            "他端新商户",
            ExpenseEditFormValues.fromConfirmation(baseline.copy(merchant = "他端新商户"), unchangedDecoded).merchant,
        )

        val clearedEncoded = ExpenseFactInputCodec.encode(
            ExpenseFactInputDraft(
                baseline = baseline,
                fundingJson = "[]",
                confirmationChanges = draft.copy(
                    amountCents = null,
                    originalAmountMinor = null,
                    clearAmount = true,
                    merchant = "",
                ).toPatchPayload(baseline),
            ),
        )
        assertTrue(clearedEncoded.contains("\"merchant\":\"\""))
        assertTrue(clearedEncoded.contains("\"original_amount\":null"))
        val clearedDecoded = ExpenseFactInputCodec.decode(clearedEncoded, baseline.id).confirmationChanges
        assertEquals("", clearedDecoded?.merchant)
        assertEquals(true, clearedDecoded?.clearOriginalAmount)
        val clearedForm = ExpenseEditFormValues.fromConfirmation(baseline, clearedDecoded)
        assertEquals("", clearedForm.merchant)
        assertEquals("", clearedForm.amountText)

        val updatedEncoded = ExpenseFactInputCodec.encode(
            ExpenseFactInputDraft(
                baseline = baseline,
                fundingJson = "[]",
                confirmationChanges = draft.copy(merchant = "新商家").toPatchPayload(baseline),
            ),
        )
        val updatedDecoded = ExpenseFactInputCodec.decode(updatedEncoded, baseline.id).confirmationChanges
        assertEquals("新商家", updatedDecoded?.merchant)
        assertEquals("新商家", ExpenseEditFormValues.fromConfirmation(baseline, updatedDecoded).merchant)
    }
}
