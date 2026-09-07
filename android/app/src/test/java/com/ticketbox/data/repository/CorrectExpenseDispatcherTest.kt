package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseCorrectionRequestDto
import com.ticketbox.data.remote.dto.ExpenseCorrectionResponseDto
import com.ticketbox.data.remote.dto.ExpenseRevisionDto
import com.ticketbox.notification.budget.CheckerHarness
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertSame
import kotlin.test.assertTrue

internal class CorrectExpenseDispatcherTest : ExpensePendingRepositoryOutboxTestBase() {
    private fun revision() = ExpenseRevisionDto(
        publicId = "revision-public",
        revisionNumber = 2L,
        changeKind = "correction",
        reason = "金额录错了",
        changedFields = listOf("amount_cents"),
        before = mapOf("amount_cents" to 12345.0),
        after = mapOf("amount_cents" to 15000.0),
        actorAccountName = "我",
        actorDeviceName = "Pixel",
        createdAt = "2026-05-20T13:00:00Z",
    )

    private sealed interface StubResult {
        data class Success(val response: ExpenseCorrectionResponseDto) : StubResult
        data class Throw(val error: Throwable) : StubResult
    }

    private class Stub(
        private val result: StubResult,
    ) : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
        var lastId: String? = null
        var lastRequest: ExpenseCorrectionRequestDto? = null
        var lastKey: String? = null
        var calls = 0

        override suspend fun correctExpense(
            id: String,
            request: ExpenseCorrectionRequestDto,
            idempotencyKey: String?,
        ): ExpenseCorrectionResponseDto {
            calls++
            lastId = id
            lastRequest = request
            lastKey = idempotencyKey
            return when (val current = result) {
                is StubResult.Success -> current.response
                is StubResult.Throw -> throw current.error
            }
        }
    }

    private fun row(key: String? = "correction-key") = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.CorrectExpense,
        targetId = "expense:42",
        ownerKey = testOutboxBinding().ownerStorageKey,
        payloadJson = com.ticketbox.OutboxAdapterGraph().correctionAdapter.toJson(
            ExpenseCorrectionPayload(1, 42, "原商家", "CNY", 12345, "CNY", testOutboxBinding().ownerStorageKey,
                "owner", "session", "binding", ExpenseCorrectionRequestDto(7, "金额录错了", amountCents = 15000))),
        expectedRowVersion = 7L,
        status = PendingMutationStatus.InFlight,
        retryCount = 0,
        lastError = null,
        createdAt = "2026-05-20T12:00:00Z",
        attemptedAt = "2026-05-20T12:00:00Z",
        completedAt = null,
        idempotencyKey = key,
    )

    @Test
    fun `success reuses original key and token and caches authoritative expense`() = runTest {
        val response = ExpenseCorrectionResponseDto(
            expense = successExpenseDto().copy(
                status = "confirmed",
                rowVersion = 8L,
                factRevision = 2L,
            ),
            revision = revision(),
        )
        val stub = Stub(StubResult.Success(response))
        var cached: Pair<String, Long>? = null
        val dispatcher = CorrectExpenseDispatcher(
            apiProvider = { stub },
            payloadAdapter = com.ticketbox.OutboxAdapterGraph().correctionAdapter,
            publishAuthoritativeProjection = { row, dto -> cached = row.ledgerId to dto.factRevision },
            onConfirmedCommitted = {},
        )

        val result = dispatcher.dispatch(row())

        assertEquals("42", stub.lastId)
        assertEquals("correction-key", stub.lastKey)
        assertEquals(7L, stub.lastRequest?.expectedRowVersion)
        assertEquals("金额录错了", stub.lastRequest?.reason)
        assertEquals("owner" to 2L, cached)
        assertEquals(DispatchResult.Success(newRowVersion = 8L), result)
    }

    @Test
    fun `missing key fails without calling server`() = runTest {
        val stub = Stub(StubResult.Throw(AssertionError("server must not be called")))
        val dispatcher = CorrectExpenseDispatcher(
            apiProvider = { stub },
            payloadAdapter = com.ticketbox.OutboxAdapterGraph().correctionAdapter,
            publishAuthoritativeProjection = { _, _ -> },
            onConfirmedCommitted = {},
        )

        assertTrue(dispatcher.dispatch(row(key = null)) is DispatchResult.Failure)
    }

    @Test
    fun `an empty persisted correction cannot dispatch or offer original retry`() = runTest {
        val adapter = com.ticketbox.OutboxAdapterGraph().correctionAdapter
        val original = row()
        val intent = requireNotNull(adapter.fromJson(original.payloadJson))
        val empty = original.copy(status = PendingMutationStatus.Failed,
            payloadJson = adapter.toJson(intent.copy(request = ExpenseCorrectionRequestDto(7, "Reason without a change"))))
        val stub = Stub(StubResult.Success(ExpenseCorrectionResponseDto(successExpenseDto(), revision())))
        val dispatcher = CorrectExpenseDispatcher({ stub }, adapter, { _, _ -> }, {})

        assertEquals(DispatchResult.Failure("correction_requires_review"), dispatcher.dispatch(empty))
        assertEquals(0, stub.calls)
        val pending = PendingExpenseCorrection(empty, adapter.readSupportedCorrection(empty))
        assertEquals(false, pending.hasSupportedIntent)
        assertEquals(false, pending.canRetry)
        for (request in listOf(ExpenseCorrectionRequestDto(7, "Clear note", note = ""),
                ExpenseCorrectionRequestDto(7, "Clear items", items = emptyList()),
                ExpenseCorrectionRequestDto(7, "Clear time", expenseTime =
                    com.ticketbox.data.remote.dto.CorrectionOptionalString.changed(null)),
                ExpenseCorrectionRequestDto(7, "Legal boundaries", originalCurrencyCode = "CNY",
                    originalAmountMinor = com.ticketbox.domain.model.MONEY_MINOR_MAX,
                    valueScore = com.ticketbox.data.remote.dto.CorrectionOptionalInt.changed(1),
                    regretScore = com.ticketbox.data.remote.dto.CorrectionOptionalInt.changed(5),
                    items = listOf(com.ticketbox.data.remote.dto.ExpenseItemRequestDto("Item", "discount",
                        quantityText = "x".repeat(64), unitPriceCents = 0, amountCents = -com.ticketbox.domain.model.MONEY_MINOR_MAX,
                        category = "x".repeat(64), rawText = "x".repeat(1000), confidence = 0.0)),
                    splits = listOf(com.ticketbox.data.remote.dto.ExpenseSplitRequestDto(1,
                        com.ticketbox.domain.model.MONEY_MINOR_MAX, "x".repeat(200)))))) {
            val changed = empty.copy(payloadJson = adapter.toJson(intent.copy(request = request)))
            assertEquals(request, adapter.readSupportedCorrection(changed)?.request)
        }
    }

    @Test
    fun `state conflict stays user resolvable`() = runTest {
        val stub = Stub(
            StubResult.Throw(
                httpException(
                    409,
                    """{"error":"state_conflict","message":"账单已被其它端修改"}""",
                ),
            ),
        )
        val dispatcher = CorrectExpenseDispatcher(
            apiProvider = { stub },
            payloadAdapter = com.ticketbox.OutboxAdapterGraph().correctionAdapter,
            publishAuthoritativeProjection = { _, _ -> },
            onConfirmedCommitted = {},
        )

        assertTrue(dispatcher.dispatch(row()) is DispatchResult.Conflict)
    }

    @Test
    fun `invalid persisted field constraints keep the original readable without transport or retry`() = runTest {
        val adapter = com.ticketbox.OutboxAdapterGraph().correctionAdapter
        val original = row()
        val payload = requireNotNull(adapter.fromJson(original.payloadJson))
        val request = payload.request
        val item = com.ticketbox.data.remote.dto.ExpenseItemRequestDto("Item")
        val split = com.ticketbox.data.remote.dto.ExpenseSplitRequestDto(1, 1)
        val maximum = com.ticketbox.domain.model.MONEY_MINOR_MAX
        val invalid = listOf(
            request.copy(splits = listOf(split.copy(memberId = 0))),
            request.copy(splits = listOf(split.copy(amountCents = maximum + 1))),
            request.copy(splits = listOf(split.copy(note = "x".repeat(201)))),
            request.copy(items = listOf(item.copy(name = ""))),
            request.copy(items = listOf(item.copy(kind = "unknown"))),
            request.copy(items = listOf(item.copy(quantityText = "x".repeat(65)))),
            request.copy(items = listOf(item.copy(unitPriceCents = -1))),
            request.copy(items = listOf(item.copy(amountCents = -1))),
            request.copy(items = listOf(item.copy(kind = "discount", amountCents = 1))),
            request.copy(items = listOf(item.copy(amountCents = maximum + 1))),
            request.copy(items = listOf(item.copy(category = "x".repeat(65)))),
            request.copy(items = listOf(item.copy(rawText = "x".repeat(1001)))),
            request.copy(items = listOf(item.copy(confidence = 1.1))),
            request.copy(amountCents = -1), request.copy(originalAmountMinor = maximum + 1),
            request.copy(originalCurrencyCode = "CN"),
            request.copy(valueScore = com.ticketbox.data.remote.dto.CorrectionOptionalInt.changed(0)),
            request.copy(regretScore = com.ticketbox.data.remote.dto.CorrectionOptionalInt.changed(6)),
        )
        val stub = Stub(StubResult.Success(ExpenseCorrectionResponseDto(successExpenseDto(), revision())))
        val dispatcher = CorrectExpenseDispatcher({ stub }, adapter, { _, _ -> }, {})
        for (invalidRequest in invalid) {
            val retained = original.copy(status = PendingMutationStatus.Failed,
                payloadJson = adapter.toJson(payload.copy(request = invalidRequest)))
            assertEquals(DispatchResult.Failure("correction_requires_review"), dispatcher.dispatch(retained), invalidRequest.toString())
            assertEquals(invalidRequest, adapter.readDisplayCorrection(retained))
            val pending = PendingExpenseCorrection(retained, adapter.readSupportedCorrection(retained))
            assertEquals(false, pending.canRetry)
            assertEquals(true, pending.canDiscard)
        }
        assertEquals(0, stub.calls)
    }

    @Test
    fun `explicit server validation refusal cannot offer the same immutable request as retry`() = runTest {
        val original = row()
        val adapter = com.ticketbox.OutboxAdapterGraph().correctionAdapter
        val stub = Stub(StubResult.Throw(httpException(422, """{"detail":"server validation"}""")))
        val dispatcher = CorrectExpenseDispatcher({ stub }, adapter, { _, _ -> error("No accepted fact") }, {})
        val result = dispatcher.dispatch(original)
        assertEquals(DispatchResult.Failure("correction_requires_review"), result)
        val retained = original.copy(status = PendingMutationStatus.Failed,
            lastError = (result as DispatchResult.Failure).message)
        val pending = PendingExpenseCorrection(retained, adapter.readSupportedCorrection(retained))
        assertEquals(true, pending.hasSupportedIntent)
        assertEquals(false, pending.delivered)
        assertEquals(false, pending.canRetry)
        assertEquals(true, pending.canDiscard)
        assertEquals(original.payloadJson, retained.payloadJson)
        assertEquals(1, stub.calls)
    }
    @Test
    fun `known 2xx notifies the real budget checker even when canonical cache publication fails`() = runTest {
        val response = ExpenseCorrectionResponseDto(successExpenseDto().copy(status = "confirmed", rowVersion = 8), revision())
        val stub = Stub(StubResult.Success(response))
        val budget = CheckerHarness().apply { activeLedgerId = "owner" }
        val dispatcher = CorrectExpenseDispatcher({ stub }, com.ticketbox.OutboxAdapterGraph().correctionAdapter,
            publishAuthoritativeProjection = { _, _ -> throw IOException("cache failure") },
            onConfirmedCommitted = budget.checker::checkAfterConfirmedWrite)
        assertEquals(DispatchResult.Success(8, cacheRefreshVersion = 8), dispatcher.dispatch(row()))
        assertEquals(1, budget.sourceCalls)
        assertEquals("v1:budget:owner:2026-06", budget.dispatched.single().key)
        assertEquals(5_000L, budget.dispatched.single().overspentCents)
        assertEquals(setOf("v1:budget:owner:2026-06"), budget.store.sent)
        assertEquals(7L, stub.lastRequest?.expectedRowVersion)
        assertEquals(1, stub.calls)
    }

    @Test
    fun `notification failure cannot turn a known 2xx into another send`() = runTest {
        val response = ExpenseCorrectionResponseDto(successExpenseDto().copy(status = "confirmed", rowVersion = 8), revision())
        for (cacheFails in listOf(false, true)) {
            val stub = Stub(StubResult.Success(response))
            var notificationAttempts = 0
            val dispatcher = CorrectExpenseDispatcher({ stub }, com.ticketbox.OutboxAdapterGraph().correctionAdapter,
                publishAuthoritativeProjection = { _, _ -> if (cacheFails) throw IOException("cache failure") },
                onConfirmedCommitted = { notificationAttempts++; throw IOException("notification failure") })
            assertEquals(DispatchResult.Success(8, cacheRefreshVersion = 8L.takeIf { cacheFails }), dispatcher.dispatch(row()))
            assertEquals(1, notificationAttempts)
            assertEquals(1, stub.calls)
        }
    }

    @Test
    fun `cancellation propagates after notification attempt and cannot be masked by a publication failure`() = runTest {
        val response = ExpenseCorrectionResponseDto(successExpenseDto().copy(status = "confirmed", rowVersion = 8), revision())
        for (cancelCache in listOf(false, true)) {
            val stub = Stub(StubResult.Success(response))
            val cancellation = CancellationException("publication cancelled")
            var notificationAttempts = 0
            val dispatcher = CorrectExpenseDispatcher({ stub }, com.ticketbox.OutboxAdapterGraph().correctionAdapter,
                publishAuthoritativeProjection = { _, _ -> if (cancelCache) throw cancellation else throw IOException("cache failure") },
                onConfirmedCommitted = {
                    notificationAttempts++
                    if (cancelCache) throw IOException("notification failure") else throw cancellation
                })
            assertSame(cancellation, assertFailsWith<CancellationException> { dispatcher.dispatch(row()) })
            assertEquals(1, notificationAttempts)
            assertEquals(1, stub.calls)
        }
    }

    @Test
    fun `target refusal and unknown protocol refusal stay failed and never become delivered`() = runTest {
        for (code in listOf(404, 409)) {
            val stub = Stub(StubResult.Throw(httpException(code, """{"error":"runtime_version_mismatch"}""")))
            val dispatcher = CorrectExpenseDispatcher({ stub }, com.ticketbox.OutboxAdapterGraph().correctionAdapter,
                publishAuthoritativeProjection = { _, _ -> }, onConfirmedCommitted = {})
            assertTrue(dispatcher.dispatch(row()) is DispatchResult.Failure)
        }
    }

    @Test
    fun `legacy unknown and mismatched command proof never call transport`() = runTest {
        val stub = Stub(StubResult.Throw(AssertionError("must not call")))
        val dispatcher = CorrectExpenseDispatcher({ stub }, com.ticketbox.OutboxAdapterGraph().correctionAdapter,
            publishAuthoritativeProjection = { _, _ -> }, onConfirmedCommitted = {})
        val valid = row()
        for (invalid in listOf(valid.copy(payloadJson = """{"expected_row_version":0,"reason":"old"}"""),
            valid.copy(payloadJson = "{}"), valid.copy(expectedRowVersion = 8), valid.copy(targetId = "expense:43"),
            valid.copy(ownerKey = "another owner"), valid.copy(ledgerId = "another ledger"))) {
            assertTrue(dispatcher.dispatch(invalid) is DispatchResult.Failure)
        }
        assertEquals(null, stub.lastId)
    }

}
