package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseDto

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.ApiService
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertSame
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice D-1: [ConfirmExpenseDispatcher] replay contract.
 *
 * Mirrors [PatchExpenseDispatcherTest]. Pins the idempotency-key half of the
 * offline confirm round-trip: the dispatcher replays the row's intent-time key
 * as the ``Idempotency-Key`` header (so a committed-but-unseen first attempt is
 * deduped server-side → HIT → canonical row, not a false 409), routes the new
 * ``idempotency_key_in_progress`` 409 to RETRY, keeps ``state_conflict`` ->
 * Conflict, and fails loudly on a keyless (pre-ADR) row. Reuses the
 * ``ExpensePendingRepositoryOutbox`` fixtures (``ApiServiceStub`` captures the
 * key; ``successExpenseDto`` / ``httpException`` build the responses).
 */
internal class ConfirmExpenseDispatcherTest : ExpensePendingRepositoryOutboxTestBase() {
    private val published = mutableListOf<Pair<String, ExpenseDto>>()


    private fun confirmRow(idempotencyKey: String?, targetId: String = "expense:42"): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.ConfirmExpense,
        targetId = targetId,
        payloadJson = moshi().adapter(ExpenseStateTokenRequest::class.java)
            .toJson(ExpenseStateTokenRequest(expectedRowVersion = 0L)),
        expectedRowVersion = 1L,
        status = PendingMutationStatus.InFlight,
        retryCount = 0,
        lastError = null,
        createdAt = "2026-05-20T12:00:00.000Z",
        attemptedAt = "2026-05-20T12:00:00.000Z",
        completedAt = null,
        idempotencyKey = idempotencyKey,
    )

    private fun dispatcherFor(
        stub: ApiService,
        publishExpense: suspend (String, ExpenseDto) -> Unit = { ledgerId, expense -> published += ledgerId to expense },
    ) = ConfirmExpenseDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(ExpenseStateTokenRequest::class.java),
        publishExpense = publishExpense,
    )

    @Test
    fun `accepted confirm keeps its first result independently of later cache contents`() = runTest {
        val original = confirmationResponse(successExpenseDto().copy(status = "confirmed", merchant = "Original merchant",
            amountCents = 12860L, originalCurrencyCode = "JPY", originalAmountMinor = 2850L))
        val current = original.copy(merchant = "Later correction", amountCents = 9900L, rowVersion = 9L,
            imageDeletedAt = "2026-05-21T13:00:00Z")
        val stub = ApiServiceStub(confirmExpenseResult = ApiResult.Success(current))
        val row = confirmRow(idempotencyKey = "original-confirm")
        val result = dispatcherFor(stub).dispatch(row) as DispatchResult.Success
        val retained = expenseConfirmationReceiptSnapshot(row.copy(status = PendingMutationStatus.Done, receiptJson = result.receiptJson))
        assertEquals(original.confirmationReceipt, retained)
        assertEquals(current, published.single().second)
        assertEquals(9L, result.newRowVersion)
    }

    @Test
    fun `accepted confirm retains its receipt when cache publication fails`() = runTest {
        val response = confirmationResponse()
        val stub = ApiServiceStub(confirmExpenseResult = ApiResult.Success(response))
        val row = confirmRow(idempotencyKey = "cache-failure-key", targetId = "expense:local:original-create")
        val api = object : ApiService by stub {
            override suspend fun confirmExpense(
                id: String,
                request: ExpenseStateTokenRequest,
                idempotencyKey: String?,
            ): ExpenseDto {
                assertEquals("local:original-create", id)
                assertEquals(ExpenseStateTokenRequest(expectedRowVersion = row.expectedRowVersion), request)
                return stub.confirmExpense(id, request, idempotencyKey)
            }
        }
        var publicationAttempts = 0
        val result = dispatcherFor(api) { ledgerId, expense ->
            assertEquals(row.ledgerId, ledgerId)
            assertEquals(response, expense)
            publicationAttempts++
            throw IllegalStateException("cache unavailable")
        }.dispatch(row)

        assertEquals(row.idempotencyKey, stub.lastConfirmIdempotencyKey)
        assertEquals(1, publicationAttempts)
        assertEquals(DispatchResult.Success(newRowVersion = 2L, cacheRefreshVersion = 2L,
            receiptJson = expenseAcceptanceReceiptJson(requireNotNull(response.confirmationReceipt))), result)
    }

    @Test
    fun `dispatch replays the row's idempotency key and returns the new row_version`() = runTest {
        val original = confirmationResponse()
        val stub = ApiServiceStub(confirmExpenseResult = ApiResult.Success(original))

        val result = dispatcherFor(stub).dispatch(confirmRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastConfirmIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = 2L,
            receiptJson = expenseAcceptanceReceiptJson(requireNotNull(original.confirmationReceipt))), result)
        assertEquals(listOf("owner" to original), published)
    }

    @Test
    fun `dispatch sends a device-local ref straight to the API instead of discarding it`() = runTest {
        // issue #65 slice 3b: before the str-ref widening, a local:{client_ref}
        // targetId failed toLongOrNull() and was Discarded; now it dispatches.
        val original = confirmationResponse()
        val stub = ApiServiceStub(confirmExpenseResult = ApiResult.Success(original))

        val result = dispatcherFor(stub)
            .dispatch(confirmRow(idempotencyKey = "key-abc", targetId = "expense:local:abc-123"))

        assertEquals("local:abc-123", stub.lastConfirmId, "the local ref must reach the API path param")
        assertEquals(DispatchResult.Success(newRowVersion = 2L,
            receiptJson = expenseAcceptanceReceiptJson(requireNotNull(original.confirmationReceipt))), result)
    }

    @Test
    fun `missing or mismatched original receipt cannot become an accepted current snapshot`() = runTest {
        val valid = confirmationResponse()
        val responses = listOf(valid.copy(confirmationReceipt = null), valid.copy(
            confirmationReceipt = requireNotNull(valid.confirmationReceipt).copy(id = 99L)))
        for (response in responses) {
            val result = dispatcherFor(ApiServiceStub(confirmExpenseResult = ApiResult.Success(response)))
                .dispatch(confirmRow(idempotencyKey = "original-confirm"))
            assertEquals(DispatchResult.Failure(EXPENSE_CONFIRMATION_ORIGINAL_REQUIRES_REVIEW), result)
        }
        assertTrue(published.isEmpty())
    }

    @Test
    fun `cancellation leaves the original confirmation unsettled`() = runTest {
        val cancellation = CancellationException("cancel original confirmation")
        val stub = ApiServiceStub(confirmExpenseResult = ApiResult.Throw(cancellation))
        val row = confirmRow(idempotencyKey = "original-confirm")
        val actual = assertFailsWith<CancellationException> { dispatcherFor(stub).dispatch(row) }
        assertSame(cancellation, actual)
        assertEquals(row.idempotencyKey, stub.lastConfirmIdempotencyKey)
        assertTrue(published.isEmpty())
    }

    @Test
    fun `a row with no idempotency key fails loudly instead of silently dropping`() = runTest {
        val stub = ApiServiceStub(confirmExpenseResult = ApiResult.Success(successExpenseDto()))

        val result = dispatcherFor(stub).dispatch(confirmRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun `409 idempotency_key_in_progress is retried, not dropped`() = runTest {
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = ApiServiceStub(confirmExpenseResult = ApiResult.Throw(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(confirmRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun `409 state_conflict still surfaces as a Conflict row`() = runTest {
        val body = """{"error":"state_conflict","message":"账单已被其它端修改"}"""
        val stub = ApiServiceStub(confirmExpenseResult = ApiResult.Throw(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(confirmRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
    }
}
