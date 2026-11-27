package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseSplitReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseSplitsResponseDto
import kotlinx.coroutines.flow.first
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice E-1: [ReplaceSplitsDispatcher] replay contract.
 *
 * Mirrors [ReplaceItemsDispatcherTest]: replays the row's intent-time key,
 * routes ``idempotency_key_in_progress`` -> RETRY, keeps ``state_conflict`` ->
 * Conflict, fails loud on a keyless row. The splits wrapper carries the parent
 * expense's bumped ``row_version``, surfaced as ``Success.newRowVersion`` for
 * the same-target cascade.
 */
class ReplaceSplitsDispatcherTest {

    private fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private fun splitsResponse(rowVersion: Long): ExpenseSplitsResponseDto = ExpenseSplitsResponseDto(
        expenseId = 42L,
        rowVersion = rowVersion,
        parentAmountCents = 12345L,
        splitsTotalAmountCents = 12345L,
        mismatchCents = 0L,
        splits = emptyList(),
    )

    private fun splitsRow(idempotencyKey: String?): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.ReplaceSplits,
        targetId = "expense:42",
        payloadJson = moshi().adapter(ExpenseSplitReplaceRequestDto::class.java)
            .toJson(ExpenseSplitReplaceRequestDto(expectedRowVersion = 0L, splits = emptyList())),
        expectedRowVersion = 1L,
        status = PendingMutationStatus.InFlight,
        retryCount = 0,
        lastError = null,
        createdAt = "2026-05-20T12:00:00.000Z",
        attemptedAt = "2026-05-20T12:00:00.000Z",
        completedAt = null,
        idempotencyKey = idempotencyKey,
    )

    private class Stub(
        private val result: Result<ExpenseSplitsResponseDto>,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        var lastIdempotencyKey: String? = null
            private set

        override suspend fun replaceExpenseSplits(
            id: String,
            request: ExpenseSplitReplaceRequestDto,
            idempotencyKey: String?,
        ): ExpenseSplitsResponseDto {
            lastIdempotencyKey = idempotencyKey
            return result.getOrThrow()
        }
    }

    private fun dispatcherFor(stub: ApiService) = ReplaceSplitsDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(ExpenseSplitReplaceRequestDto::class.java),
    )

    @Test
    fun `dispatch replays the row's idempotency key and returns the parent row_version`() = runTest {
        val stub = Stub(Result.success(splitsResponse(rowVersion = 2L)))

        val result = dispatcherFor(stub).dispatch(splitsRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = 2L), result)
    }

    @Test
    fun `a row with no idempotency key fails loudly instead of silently dropping`() = runTest {
        val stub = Stub(Result.success(splitsResponse(rowVersion = 2L)))

        val result = dispatcherFor(stub).dispatch(splitsRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun `409 idempotency_key_in_progress is retried, not dropped`() = runTest {
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(splitsRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun `409 state_conflict still surfaces as a Conflict row`() = runTest {
        val body = """{"error":"state_conflict","message":"账单已被其它端修改"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(splitsRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
    }

    @Test
    fun `404 member_not_found returns visible definitelyRejected Failure instead of Discarded`() = runTest {
        val body = """{"error":"member_not_found","message":"成员不存在或已停用。"}"""
        val stub = Stub(Result.failure(httpException(404, body)))

        val result = dispatcherFor(stub).dispatch(splitsRow(idempotencyKey = "key-abc"))

        assertEquals(DispatchResult.Failure("成员不存在或已停用。", definitelyRejected = true), result)
    }

    @Test
    fun `404 member_not_found stays FAILED in OutboxDrainEngine and never becomes done`() = runTest {
        val body = """{"error":"member_not_found","message":"成员不存在或已停用。"}"""
        val stub = Stub(Result.failure(httpException(404, body)))
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val payloadJson = moshi().adapter(ExpenseSplitReplaceRequestDto::class.java)
            .toJson(ExpenseSplitReplaceRequestDto(expectedRowVersion = 0L, splits = emptyList()))
        val rowId = outbox.enqueue(
            type = PendingMutationType.ReplaceSplits,
            targetId = "expense:42",
            payloadJson = payloadJson,
            expectedRowVersion = 1L,
            idempotencyKey = "key-member-404",
        )
        dao.runnableBatches += listOf(rowId)

        val summary = OutboxDrainEngine(outbox, listOf(dispatcherFor(stub))).drainOnce()

        assertEquals(1, summary.attempted)
        assertEquals(0, summary.done)
        assertEquals(0, summary.discarded)
        assertEquals(1, summary.failures)
        val stored = dao.rows.getValue(rowId)
        assertEquals(PendingMutationStatus.Failed.wireValue, stored.status)
        assertEquals("成员不存在或已停用。", stored.lastError)
        assertNull(stored.completedAt)
        val failedRows = outbox.observeStatus().first().failed
        assertEquals(listOf(rowId), failedRows.map { it.id })
    }

    @Test
    fun `404 expense_not_found still discards while unknown 404 stays Failure`() = runTest {
        val gone = Stub(Result.failure(httpException(404, """{"error":"expense_not_found","message":"账单不存在。"}""")))
        assertEquals(
            DispatchResult.Discarded("账单不存在。"),
            dispatcherFor(gone).dispatch(splitsRow(idempotencyKey = "key-abc")),
        )

        val missingRoute = Stub(Result.failure(httpException(404, """{"error":"route_not_found","message":"没有找到这个功能入口。"}""")))
        assertEquals(
            DispatchResult.Failure("账本版本过旧，请重启电脑上的小票夹后再试。", definitelyRejected = true),
            dispatcherFor(missingRoute).dispatch(splitsRow(idempotencyKey = "key-abc")),
        )
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
            retrofit2.Response.error<ExpenseSplitsResponseDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
