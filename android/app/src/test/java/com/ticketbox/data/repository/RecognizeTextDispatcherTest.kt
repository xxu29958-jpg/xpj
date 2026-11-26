package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import java.io.IOException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice E-2: [RecognizeTextDispatcher] replay contract.
 *
 * Body-carrying like [ReplaceItemsDispatcherTest]: replays the row's intent-time
 * key, publishes the current projection without returning a cascade token, routes
 * ``idempotency_key_in_progress`` -> RETRY, keeps ``state_conflict`` -> Conflict,
 * fails loud on a keyless row, and preserves ``rawText`` across ``copy(expectedRowVersion=…)``.
 */
class RecognizeTextDispatcherTest {
    private val published = mutableListOf<Pair<String, ExpenseDto>>()


    private fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private fun recognizedExpenseDto(rowVersion: Long): ExpenseDto = ExpenseDto(
        homeCurrency = "CNY",
        originalCurrencyCode = "CNY",
        id = 42L,
        publicId = "test-public-id",
        amountCents = 3500L,
        merchant = "星巴克",
        category = "餐饮",
        note = "",
        source = "Android截图",
        imagePath = null,
        thumbnailPath = null,
        imageHash = null,
        rawText = "星巴克 拿铁 ¥35",
        confidence = null,
        duplicateStatus = "none",
        duplicateOfId = null,
        duplicateReason = null,
        tags = null,
        valueScore = null,
        regretScore = null,
        status = "pending",
        expenseTime = "2026-05-20T12:00:00Z",
        createdAt = "2026-05-20T12:00:00Z",
        updatedAt = "2026-05-20T13:00:00.000Z",
        rowVersion = rowVersion,
        confirmedAt = null,
        rejectedAt = null,
    )

    private fun recognizeTextRow(idempotencyKey: String?): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.RecognizeText,
        targetId = "expense:42",
        // Token stripped to 0 in the payload (the row's expectedRowVersion is the
        // source of truth); the pasted raw_text stays so the replay re-sends it.
        payloadJson = moshi().adapter(ExpenseRecognizeTextRequestDto::class.java)
            .toJson(ExpenseRecognizeTextRequestDto(expectedRowVersion = 0L, rawText = "星巴克 拿铁 ¥35")),
        expectedRowVersion = 7L,
        status = PendingMutationStatus.InFlight,
        retryCount = 0,
        lastError = null,
        createdAt = "2026-05-20T12:00:00.000Z",
        attemptedAt = "2026-05-20T12:00:00.000Z",
        completedAt = null,
        idempotencyKey = idempotencyKey,
    )

    private class Stub(
        private val result: Result<ExpenseDto>,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        var lastIdempotencyKey: String? = null
            private set
        var lastRequest: ExpenseRecognizeTextRequestDto? = null
            private set

        override suspend fun recognizeText(
            id: String,
            request: ExpenseRecognizeTextRequestDto,
            idempotencyKey: String?,
        ): ExpenseDto {
            lastIdempotencyKey = idempotencyKey
            lastRequest = request
            return result.getOrThrow()
        }
    }

    private fun dispatcherFor(
        stub: ApiService,
        publishExpense: suspend (String, ExpenseDto) -> Unit = { ledgerId, expense -> published += ledgerId to expense },
    ) = RecognizeTextDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(ExpenseRecognizeTextRequestDto::class.java),
        publishExpense = publishExpense,
    )

    @Test
    fun `accepted text recognition retains its receipt when cache publication fails`() = runTest {
        val response = recognizedExpenseDto(rowVersion = 8L)
        val stub = Stub(Result.success(response))
        val row = recognizeTextRow(idempotencyKey = "cache-failure-key")
        var publicationAttempts = 0
        val result = dispatcherFor(stub) { ledgerId, expense ->
            assertEquals(row.ledgerId, ledgerId)
            assertEquals(response, expense)
            publicationAttempts++
            throw IllegalStateException("cache unavailable")
        }.dispatch(row)

        val expectedRequest = requireNotNull(moshi().adapter(ExpenseRecognizeTextRequestDto::class.java).fromJson(row.payloadJson))
            .copy(expectedRowVersion = row.expectedRowVersion)
        assertEquals(row.idempotencyKey, stub.lastIdempotencyKey)
        assertEquals(expectedRequest, stub.lastRequest)
        assertEquals(1, publicationAttempts)
        assertEquals(DispatchResult.Success(newRowVersion = null, cacheRefreshVersion = 8L,
            receiptJson = """{"expenseId":42}"""), result)
    }

    @Test
    fun `dispatch replays the row's idempotency key without returning a cascade token`() = runTest {
        val stub = Stub(Result.success(recognizedExpenseDto(rowVersion = 8L)))

        val result = dispatcherFor(stub).dispatch(recognizeTextRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = null), result)
        assertEquals(listOf("owner" to recognizedExpenseDto(rowVersion = 8L)), published)
    }

    @Test
    fun `replayed RecognizeText refreshes cache without cascading latest version onto queued ReplaceSplits`() = runTest {
        var serverRowVersion = 7L
        val committedRecognizeKeys = mutableSetOf<String>()
        val recognizeAttempts = mutableListOf<Pair<String, Long>>()
        val splitTokensSent = mutableListOf<Long>()
        val api = object : ApiService by FakeApiService(mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun recognizeText(
                id: String,
                request: ExpenseRecognizeTextRequestDto,
                idempotencyKey: String?,
            ): ExpenseDto {
                val key = requireNotNull(idempotencyKey)
                recognizeAttempts += key to request.expectedRowVersion
                if (key !in committedRecognizeKeys) {
                    assertEquals(serverRowVersion, request.expectedRowVersion)
                    committedRecognizeKeys += key
                    serverRowVersion = 8L
                    throw IOException("connection dropped after server commit")
                }
                return recognizedExpenseDto(rowVersion = serverRowVersion)
            }

            override suspend fun replaceExpenseSplits(
                id: String,
                request: ExpenseSplitReplaceRequestDto,
                idempotencyKey: String?,
            ): ExpenseSplitsResponseDto {
                splitTokensSent += request.expectedRowVersion
                if (request.expectedRowVersion != serverRowVersion) {
                    throw httpException(409, """{"error":"state_conflict","message":"账单已被其它端修改"}""")
                }
                error("Stale queued ReplaceSplits must never silently overwrite concurrent v9 edits")
            }
        }
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val recognizeId = outbox.enqueue(
            type = PendingMutationType.RecognizeText,
            targetId = "expense:42",
            payloadJson = moshi().adapter(ExpenseRecognizeTextRequestDto::class.java)
                .toJson(ExpenseRecognizeTextRequestDto(expectedRowVersion = 0L, rawText = "星巴克 拿铁 ¥35")),
            expectedRowVersion = 7L,
            idempotencyKey = "key-recognize-replay",
        )
        val splitsId = outbox.enqueue(
            type = PendingMutationType.ReplaceSplits,
            targetId = "expense:42",
            payloadJson = moshi().adapter(ExpenseSplitReplaceRequestDto::class.java)
                .toJson(ExpenseSplitReplaceRequestDto(expectedRowVersion = 0L, splits = listOf(ExpenseSplitRequestDto(1L, 3500L)))),
            expectedRowVersion = 7L,
            idempotencyKey = "key-splits",
        )
        dao.tokenCascadeIds += listOf(splitsId)
        val engine = OutboxDrainEngine(
            outbox,
            listOf(
                dispatcherFor(api),
                ReplaceSplitsDispatcher({ api }, moshi().adapter(ExpenseSplitReplaceRequestDto::class.java)),
            ),
        )

        dao.runnableBatches += listOf(recognizeId)
        val droppedDrain = engine.drainOnce()
        assertEquals(1, droppedDrain.retryable)
        assertEquals(8L, serverRowVersion)
        assertTrue(published.isEmpty())
        assertEquals(PendingMutationStatus.Pending.wireValue, dao.rows.getValue(recognizeId).status)
        assertEquals(7L, dao.rows.getValue(splitsId).expectedRowVersion)

        serverRowVersion = 9L

        dao.runnableBatches += listOf(recognizeId)
        val replayDrain = engine.drainOnce()
        assertEquals(1, replayDrain.done)
        assertEquals(listOf("key-recognize-replay" to 7L, "key-recognize-replay" to 7L), recognizeAttempts)
        assertEquals(listOf("owner" to recognizedExpenseDto(rowVersion = 9L)), published)
        assertTrue(dao.tokenCascadeCalls.isEmpty())
        assertEquals(7L, dao.rows.getValue(splitsId).expectedRowVersion)

        dao.runnableBatches += listOf(splitsId)
        val splitsDrain = engine.drainOnce()
        assertEquals(1, splitsDrain.conflicts)
        assertEquals(listOf(7L), splitTokensSent)
        assertEquals(PendingMutationStatus.Conflict.wireValue, dao.rows.getValue(splitsId).status)
    }

    @Test
    fun `OutboxDrainEngine suppresses cascade even if RecognizeText dispatcher returns a token`() = runTest {
        val guardDao = FakePendingMutationDao()
        val guardOutbox = testOutboxRepository(guardDao)
        val guardedRecognizeId = guardOutbox.enqueue(PendingMutationType.RecognizeText, "expense:42", "{}", 7L, "k-guard")
        val guardedSplitsId = guardOutbox.enqueue(PendingMutationType.ReplaceSplits, "expense:42", "{}", 7L, "k-guard-splits")
        guardDao.tokenCascadeIds += listOf(guardedSplitsId)
        guardDao.runnableBatches += listOf(guardedRecognizeId)
        val syntheticDispatcher = object : OutboxMutationDispatcher {
            override val type = PendingMutationType.RecognizeText
            override suspend fun dispatch(row: OutboxRow) = DispatchResult.Success(newRowVersion = 9L)
        }
        assertEquals(1, OutboxDrainEngine(guardOutbox, listOf(syntheticDispatcher)).drainOnce().done)
        assertTrue(guardDao.tokenCascadeCalls.isEmpty())
        assertEquals(7L, guardDao.rows.getValue(guardedSplitsId).expectedRowVersion)
    }

    @Test
    fun `dispatch overwrites only the token, the pasted raw_text survives the copy`() = runTest {
        val stub = Stub(Result.success(recognizedExpenseDto(rowVersion = 8L)))

        dispatcherFor(stub).dispatch(recognizeTextRow(idempotencyKey = "key-abc"))

        val sent = requireNotNull(stub.lastRequest) { "recognizeText must have been called" }
        // Token taken from the row (7), NOT the payload's stripped 0.
        assertEquals(7L, sent.expectedRowVersion, "dispatcher must overwrite the token from the row")
        // The pasted text is NOT lost when the token is copied over.
        assertEquals("星巴克 拿铁 ¥35", sent.rawText, "raw_text must survive copy(expectedRowVersion=…)")
    }

    @Test
    fun `a row with no idempotency key fails loudly instead of silently dropping`() = runTest {
        val stub = Stub(Result.success(recognizedExpenseDto(rowVersion = 8L)))

        val result = dispatcherFor(stub).dispatch(recognizeTextRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun `409 idempotency_key_in_progress is retried, not dropped`() = runTest {
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(recognizeTextRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun `409 state_conflict still surfaces as a Conflict row`() = runTest {
        val body = """{"error":"state_conflict","message":"账单已被其它端修改"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(recognizeTextRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
    }

    @Test
    fun `404 expense_not_found stays Failed in OutboxDrainEngine instead of discarding`() = runTest {
        val body = """{"error":"expense_not_found","message":"账单不存在。"}"""
        val directResult = dispatcherFor(Stub(Result.failure(httpException(404, body))))
            .dispatch(recognizeTextRow(idempotencyKey = "key-404"))
        assertEquals(DispatchResult.Failure("账单不存在。", definitelyRejected = true), directResult)

        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val payloadJson = moshi().adapter(ExpenseRecognizeTextRequestDto::class.java)
            .toJson(ExpenseRecognizeTextRequestDto(expectedRowVersion = 0L, rawText = "星巴克 拿铁 ¥35"))
        val rowId = outbox.enqueue(
            type = PendingMutationType.RecognizeText,
            targetId = "expense:42",
            payloadJson = payloadJson,
            expectedRowVersion = 7L,
            idempotencyKey = "key-404",
        )
        dao.runnableBatches += listOf(rowId)

        val summary = OutboxDrainEngine(outbox, listOf(dispatcherFor(Stub(Result.failure(httpException(404, body)))))).drainOnce()
        assertEquals(1, summary.failures)
        assertEquals(0, summary.done)
        assertEquals(0, summary.discarded)
        val failedRow = dao.rows.getValue(rowId)
        assertEquals(PendingMutationStatus.Failed.wireValue, failedRow.status)
        assertEquals("账单不存在。", failedRow.lastError)
        assertNull(failedRow.completedAt)
    }

    private fun httpException(code: Int, body: String): HttpException {
        val raw = Response.Builder()
            .protocol(Protocol.HTTP_1_1)
            .request(Request.Builder().url("https://api.example.com/").build())
            .code(code)
            .message("test")
            .body(body.toResponseBody("application/json".toMediaTypeOrNull()))
            .build()
        return HttpException(
            retrofit2.Response.error<ExpenseDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
