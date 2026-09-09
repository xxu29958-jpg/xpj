package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseManualCreateRequestDto
import kotlinx.coroutines.test.runTest
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * issue #65 slice 4: [CreateExpenseDispatcher] replay contract for the offline
 * manual create (``POST /api/expenses/manual``).
 *
 * Unlike the OCC-token dispatchers, idempotency rides the body ``client_ref`` (not
 * a header / row_version). Pins: the dispatcher sends the payload's ``client_ref``,
 * writes the server-assigned identity back (resolved by clientRef) on success and
 * returns the new row_version, FAILs loudly on a keyless row, retries on
 * IOException, FAILs visibly on a 422, and — crucially — RETRIES (not FAILS) when
 * the create committed server-side but the local write-back throws (a re-POST is
 * idempotent via client_ref, so failing would risk a duplicate).
 */
internal class CreateExpenseDispatcherTest : ExpensePendingRepositoryOutboxTestBase() {

    private class CapturedWriteback {
        var ledgerId: String? = null
        var clientRef: String? = null
        var created: ExpenseDto? = null
        var calls: Int = 0
    }

    private class ManualCreateApiStub(
        private val dto: ExpenseDto? = null,
        private val failure: Throwable? = null,
    ) : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
        var lastRequest: ExpenseManualCreateRequestDto? = null
            private set

        override suspend fun createManualExpense(request: ExpenseManualCreateRequestDto): ExpenseDto {
            lastRequest = request
            failure?.let { throw it }
            return requireNotNull(dto) { "ManualCreateApiStub needs a dto or a failure" }
        }
    }

    private fun manualAdapter() = moshi().adapter(ExpenseManualCreateRequestDto::class.java)

    private fun manualReceipt(): ExpenseDto = successExpenseDto().copy(originalAmountMinor = 1234,
        amountCents = 1234, source = "手动记账")

    private fun createRow(clientRef: String?, targetId: String = "expense:local:abc-123"): OutboxRow {
        val payload = manualAdapter().toJson(
            ExpenseManualCreateRequestDto(
                originalCurrency = "CNY",
                originalAmount = "12.34",
                spentAt = null,
                merchant = "新商家",
                category = "餐饮",
                note = null,
                expenseTime = "2026-05-20T12:00:00Z",
                tags = null,
                valueScore = null,
                regretScore = null,
                clientRef = clientRef,
            ),
        )
        return OutboxRow(
            id = 1L,
            serverUrl = "https://api.example.com",
            ledgerId = "owner",
            type = PendingMutationType.CreateExpense,
            targetId = targetId,
            payloadJson = payload,
            expectedRowVersion = 0L,
            status = PendingMutationStatus.InFlight,
            retryCount = 0,
            lastError = null,
            createdAt = "2026-05-20T12:00:00.000Z",
            attemptedAt = "2026-05-20T12:00:00.000Z",
            completedAt = null,
            idempotencyKey = null,
        )
    }

    private fun dispatcherFor(
        stub: ApiService,
        writeback: CapturedWriteback,
        onWriteback: suspend () -> Unit = {},
    ) = CreateExpenseDispatcher(
        apiProvider = { stub },
        payloadAdapter = manualAdapter(),
        applyServerIdentity = { ledgerId, clientRef, created ->
            writeback.calls++
            writeback.ledgerId = ledgerId
            writeback.clientRef = clientRef
            writeback.created = created
            onWriteback()
        },
    )

    @Test
    fun malformedOrDifferentMoneyReceiptsCannotPublishIdentityOrCompleteTheOriginal() = runTest {
        val row = createRow("abc-123")
        val dto = manualReceipt()
        for (bad in listOf(dto.copy(id = 0), dto.copy(publicId = null), dto.copy(rowVersion = 0),
            dto.copy(status = "rejected"), dto.copy(status = "unknown"), dto.copy(originalCurrencyCode = "JPY"),
            dto.copy(originalAmountMinor = 123400), dto.copy(homeCurrency = null), dto.copy(source = "Android截图"))) {
            val writes = CapturedWriteback()
            val result = dispatcherFor(ManualCreateApiStub(dto = bad), writes).dispatch(row)
            assertEquals(DispatchResult.Failure(MANUAL_CREATE_RECEIPT_REVIEW), result)
            assertEquals(0, writes.calls)
        }
        val body = requireNotNull(manualAdapter().fromJson(row.payloadJson)).copy(homeCurrencyCode = "CNY")
        val mismatch = row.copy(payloadJson = manualAdapter().toJson(body))
        assertEquals(DispatchResult.Failure(MANUAL_CREATE_RECEIPT_REVIEW),
            dispatcherFor(ManualCreateApiStub(dto = dto.copy(homeCurrency = "JPY")), CapturedWriteback()).dispatch(mismatch))
        val missingFx = dto.copy(status = "pending", amountCents = null, category = "自动分类")
        assertTrue(dispatcherFor(ManualCreateApiStub(dto = missingFx), CapturedWriteback()).dispatch(row) is DispatchResult.Success)
    }

    @Test
    fun `dispatch posts client_ref, writes server identity back, returns new row_version`() = runTest {
        val stub = ManualCreateApiStub(dto = manualReceipt())
        val writeback = CapturedWriteback()

        val result = dispatcherFor(stub, writeback).dispatch(createRow(clientRef = "abc-123"))

        assertEquals("abc-123", stub.lastRequest?.clientRef, "the body must carry the row's client_ref")
        assertEquals("owner", writeback.ledgerId)
        assertEquals("abc-123", writeback.clientRef, "write-back must resolve the local row by clientRef")
        assertEquals(42L, writeback.created?.id, "write-back must carry the server-assigned id")
        assertTrue(result is DispatchResult.Success)
        assertEquals(2L, result.newRowVersion)
        assertEquals("{\"expenseId\":42}", result.receiptJson)
    }

    @Test
    fun `a row missing client_ref fails loudly instead of double-creating`() = runTest {
        val stub = ManualCreateApiStub(dto = manualReceipt())
        val writeback = CapturedWriteback()

        val result = dispatcherFor(stub, writeback).dispatch(createRow(clientRef = null))

        assertTrue(result is DispatchResult.Failure, "null client_ref must FAIL visibly: $result")
        assertNull(stub.lastRequest, "the API must not be called for a malformed row")
        assertEquals(0, writeback.calls, "write-back must not run")
    }

    @Test
    fun missingOriginalCurrencyOrAmountCannotBeReinterpretedUsingTheCurrentDefault() = runTest {
        val adapter = manualAdapter()
        val original = createRow("original-ref")
        val body = requireNotNull(adapter.fromJson(original.payloadJson))
        listOf(body.copy(originalCurrency = null), body.copy(originalCurrency = ""), body.copy(originalAmount = null),
            body.copy(clientRef = " ")).forEach { malformed ->
            val stub = ManualCreateApiStub(dto = manualReceipt())
            val writeback = CapturedWriteback()
            val row = original.copy(payloadJson = adapter.toJson(malformed))
            assertTrue(dispatcherFor(stub, writeback).dispatch(row) is DispatchResult.Failure)
            assertNull(stub.lastRequest)
            assertEquals(0, writeback.calls)
        }
    }

    @Test
    fun anExplicitLegacyPaymentRetainsItsBodyWithoutSynthesizingHomeCurrency() = runTest {
        val stub = ManualCreateApiStub(dto = manualReceipt().copy(homeCurrency = "JPY"))
        val row = createRow("old-cny-intent")
        val result = dispatcherFor(stub, CapturedWriteback()).dispatch(row)
        assertTrue(result is DispatchResult.Success)
        assertEquals("CNY", stub.lastRequest?.originalCurrency)
        assertEquals("12.34", stub.lastRequest?.originalAmount)
        assertNull(stub.lastRequest?.homeCurrencyCode)
        assertEquals("old-cny-intent", stub.lastRequest?.clientRef)
    }

    @Test
    fun `IOException retries (offline) rather than failing`() = runTest {
        val stub = ManualCreateApiStub(failure = IOException("offline"))
        val writeback = CapturedWriteback()

        val result = dispatcherFor(stub, writeback).dispatch(createRow(clientRef = "abc-123"))

        assertTrue(result is DispatchResult.RetryableFailure, "IOException must retry: $result")
        assertEquals(0, writeback.calls)
    }

    @Test
    fun `422 validation rejection surfaces as a visible FAILED row`() = runTest {
        val body = """{"error":"amount_required","message":"请先填写金额。"}"""
        val stub = ManualCreateApiStub(failure = httpException(422, body))
        val writeback = CapturedWriteback()

        val result = dispatcherFor(stub, writeback).dispatch(createRow(clientRef = "abc-123"))

        assertTrue(result is DispatchResult.Failure, "422 must FAIL visibly: $result")
        assertEquals(0, writeback.calls)
    }

    @Test
    fun `missing original receipt preserves the review identity without applying a latest fact`() = runTest {
        for (expenseId in listOf<Long?>(71, null, -1)) {
            val detail = expenseId?.let { ",\"expense_id\":$it" }.orEmpty()
            val stub = ManualCreateApiStub(failure = httpException(409,
                "{\"error\":\"manual_create_original_requires_review\",\"message\":\"Review original\"$detail}"))
            val writeback = CapturedWriteback()
            val original = createRow(clientRef = "abc-123")

            val result = dispatcherFor(stub, writeback).dispatch(original)

            val suffix = expenseId?.takeIf { it > 0 }?.let { ":$it" }.orEmpty()
            assertEquals(DispatchResult.Failure("manual_create_original_requires_review$suffix"), result)
            assertEquals(0, writeback.calls)
            assertEquals("abc-123", stub.lastRequest?.clientRef)
            val refused = original.copy(status = PendingMutationStatus.Failed, lastError = (result as DispatchResult.Failure).message)
            assertTrue(refused.requiresManualCreateReview())
            assertEquals(expenseId?.takeIf { it > 0 }, refused.manualCreateReviewExpenseId())
            assertEquals(original.payloadJson, refused.payloadJson)
            assertEquals(original.idempotencyKey, refused.idempotencyKey)
        }
    }

    @Test
    fun `a write-back failure retries because the committed create re-POSTs idempotently`() = runTest {
        val stub = ManualCreateApiStub(dto = manualReceipt())
        val writeback = CapturedWriteback()

        val result = dispatcherFor(stub, writeback, onWriteback = { throw IllegalStateException("db locked") })
            .dispatch(createRow(clientRef = "abc-123"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "a committed create whose write-back throws must RETRY (re-POST HITs), not FAIL: $result",
        )
        assertEquals(1, writeback.calls, "write-back was attempted")
    }
}
