package com.ticketbox.data.repository

import com.ticketbox.data.remote.dto.ExpenseDto

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import com.ticketbox.data.remote.ApiService
import kotlinx.coroutines.test.runTest
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice D-1: [RetryOcrDispatcher] replay contract.
 *
 * Mirrors [PatchExpenseDispatcherTest]: replays the row's intent-time key,
 * routes ``idempotency_key_in_progress`` -> RETRY, keeps ``state_conflict`` ->
 * Conflict, fails loud on a keyless row.
 */
internal class RetryOcrDispatcherTest : ExpensePendingRepositoryOutboxTestBase() {
    private val published = mutableListOf<Pair<String, ExpenseDto>>()


    private fun retryOcrRow(idempotencyKey: String?): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.RetryOcr,
        targetId = "expense:42",
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
    ) = RetryOcrDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(ExpenseStateTokenRequest::class.java),
        publishExpense = publishExpense,
    )

    @Test
    fun `rejected region retains its actionable error and original key`() = runTest {
        for ((code, status) in listOf(
            "ocr_region_no_text" to 422,
            "ocr_region_incomplete" to 422,
            "ocr_region_invalid" to 422,
            "ocr_region_source_unavailable" to 409,
        )) {
            val stub = ApiServiceStub(retryOcrResult = ApiResult.Throw(
                httpException(status, """{"error":"$code","message":"请调整选区。"}"""),
            ))
            val result = dispatcherFor(stub).dispatch(retryOcrRow(idempotencyKey = "original-region-786"))
            assertTrue(result is DispatchResult.Failure)
            assertEquals(code, result.message)
            assertEquals("original-region-786", stub.lastRetryOcrIdempotencyKey)
            assertTrue(published.isEmpty())
        }
    }

    @Test
    fun `accepted OCR retry retains its receipt when cache publication fails`() = runTest {
        val response = successExpenseDto()
        val stub = ApiServiceStub(retryOcrResult = ApiResult.Success(response))
        val row = retryOcrRow(idempotencyKey = "cache-failure-key")
        val api = object : ApiService by stub {
            override suspend fun retryOcr(
                id: String,
                request: ExpenseStateTokenRequest,
                idempotencyKey: String?,
            ): ExpenseDto {
                assertEquals("42", id)
                assertEquals(ExpenseStateTokenRequest(expectedRowVersion = row.expectedRowVersion), request)
                return stub.retryOcr(id, request, idempotencyKey)
            }
        }
        var publicationAttempts = 0
        val result = dispatcherFor(api) { ledgerId, expense ->
            assertEquals(row.ledgerId, ledgerId)
            assertEquals(response, expense)
            publicationAttempts++
            throw IllegalStateException("cache unavailable")
        }.dispatch(row)

        assertEquals(row.idempotencyKey, stub.lastRetryOcrIdempotencyKey)
        assertEquals(1, publicationAttempts)
        assertEquals(DispatchResult.Success(newRowVersion = null, cacheRefreshVersion = 2L,
            receiptJson = """{"expenseId":42}"""), result)
    }

    @Test
    fun `dispatch replays the row's idempotency key without returning a cascade token`() = runTest {
        val stub = ApiServiceStub(retryOcrResult = ApiResult.Success(successExpenseDto()))

        val result = dispatcherFor(stub).dispatch(retryOcrRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastRetryOcrIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = null), result)
        assertEquals(listOf("owner" to successExpenseDto()), published)
    }

    @Test
    fun `accepted OCR retry never cascades response rowVersion onto queued ReplaceSplits`() = runTest {
        val payloadJson = moshi().adapter(ExpenseStateTokenRequest::class.java)
            .toJson(ExpenseStateTokenRequest(expectedRowVersion = 0L))
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val retryOcrId = outbox.enqueue(
            type = PendingMutationType.RetryOcr,
            targetId = "expense:42",
            payloadJson = payloadJson,
            expectedRowVersion = 7L,
            idempotencyKey = "key-retry-ocr-replay",
        )
        val replaceSplitsId = outbox.enqueue(
            type = PendingMutationType.ReplaceSplits,
            targetId = "expense:42",
            payloadJson = "{}",
            expectedRowVersion = 7L,
            idempotencyKey = "key-splits",
        )
        dao.tokenCascadeIds += listOf(replaceSplitsId)
        dao.runnableBatches += listOf(retryOcrId)

        val driftedResponse = successExpenseDto().copy(rowVersion = 9L)
        val stub = ApiServiceStub(retryOcrResult = ApiResult.Success(driftedResponse))
        val summary = OutboxDrainEngine(outbox, listOf(dispatcherFor(stub))).drainOnce()

        assertEquals(1, summary.done)
        assertTrue(dao.tokenCascadeCalls.isEmpty())
        assertEquals(7L, dao.rows.getValue(replaceSplitsId).expectedRowVersion)

        val engineGuardDao = FakePendingMutationDao()
        val engineGuardOutbox = testOutboxRepository(engineGuardDao)
        val guardedRetryId = engineGuardOutbox.enqueue(PendingMutationType.RetryOcr, "expense:42", payloadJson, 7L, "k-guard")
        val guardedSplitsId = engineGuardOutbox.enqueue(PendingMutationType.ReplaceSplits, "expense:42", "{}", 7L, "k-guard-splits")
        engineGuardDao.tokenCascadeIds += listOf(guardedSplitsId)
        engineGuardDao.runnableBatches += listOf(guardedRetryId)
        val syntheticDispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.RetryOcr
            override suspend fun dispatch(row: OutboxRow) = DispatchResult.Success(newRowVersion = 9L)
        }
        assertEquals(1, OutboxDrainEngine(engineGuardOutbox, listOf(syntheticDispatcher)).drainOnce().done)
        assertTrue(engineGuardDao.tokenCascadeCalls.isEmpty())
        assertEquals(7L, engineGuardDao.rows.getValue(guardedSplitsId).expectedRowVersion)
    }

    @Test
    fun `a row with no idempotency key fails loudly instead of silently dropping`() = runTest {
        val stub = ApiServiceStub(retryOcrResult = ApiResult.Success(successExpenseDto()))

        val result = dispatcherFor(stub).dispatch(retryOcrRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun `409 idempotency_key_in_progress is retried, not dropped`() = runTest {
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = ApiServiceStub(retryOcrResult = ApiResult.Throw(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(retryOcrRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun `409 state_conflict still surfaces as a Conflict row`() = runTest {
        val body = """{"error":"state_conflict","message":"账单已被其它端修改"}"""
        val stub = ApiServiceStub(retryOcrResult = ApiResult.Throw(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(retryOcrRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
    }

    @Test
    fun `404 task_not_found and expense_not_found both stay Failed in OutboxDrainEngine`() = runTest {
        val payloadJson = moshi().adapter(ExpenseStateTokenRequest::class.java)
            .toJson(ExpenseStateTokenRequest(expectedRowVersion = 0L))
        for ((key, targetId, body, expectedMessage) in listOf(
            listOf("key-task-404", "expense:42", """{"error":"task_not_found","message":"后台任务不存在或已结束。"}""", "后台任务不存在或已结束。"),
            listOf("key-expense-404", "expense:99", """{"error":"expense_not_found","message":"账单不存在。"}""", "账单不存在。"),
        )) {
            assertEquals(
                DispatchResult.Failure(expectedMessage, definitelyRejected = true),
                dispatcherFor(ApiServiceStub(retryOcrResult = ApiResult.Throw(httpException(404, body))))
                    .dispatch(retryOcrRow(idempotencyKey = key)),
            )

            val dao = FakePendingMutationDao()
            val outbox = testOutboxRepository(dao)
            val rowId = outbox.enqueue(
                type = PendingMutationType.RetryOcr,
                targetId = targetId,
                payloadJson = payloadJson,
                expectedRowVersion = 1L,
                idempotencyKey = key,
            )
            dao.runnableBatches += listOf(rowId)

            val stub = ApiServiceStub(retryOcrResult = ApiResult.Throw(httpException(404, body)))
            val summary = OutboxDrainEngine(outbox, listOf(dispatcherFor(stub))).drainOnce()
            assertEquals(1, summary.failures)
            assertEquals(0, summary.done)
            assertEquals(0, summary.discarded)
            val failedRow = dao.rows.getValue(rowId)
            assertEquals(PendingMutationStatus.Failed.wireValue, failedRow.status)
            assertEquals(expectedMessage, failedRow.lastError)
            assertNull(failedRow.completedAt)
        }
    }
}
