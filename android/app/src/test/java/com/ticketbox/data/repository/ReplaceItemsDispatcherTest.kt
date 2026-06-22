package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseItemReplaceRequestDto
import com.ticketbox.data.remote.dto.ExpenseItemsResponseDto
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertTrue

/**
 * ADR-0042 Slice D-2: [ReplaceItemsDispatcher] replay contract.
 *
 * Mirrors [PatchExpenseDispatcherTest]: replays the row's intent-time key,
 * routes ``idempotency_key_in_progress`` -> RETRY, keeps ``state_conflict`` ->
 * Conflict, fails loud on a keyless row. This path PRE-DATES ADR-0042 keys, so
 * the guard + replay are net-new here. The items wrapper carries the parent
 * expense's bumped ``row_version``, surfaced as ``Success.newRowVersion`` for
 * the same-target cascade.
 */
class ReplaceItemsDispatcherTest {

    private fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private fun itemsResponse(rowVersion: Long): ExpenseItemsResponseDto = ExpenseItemsResponseDto(
        expenseId = 42L,
        rowVersion = rowVersion,
        parentAmountCents = 12345L,
        itemsTotalAmountCents = 2500L,
        mismatchCents = -9845L,
        itemsSumStatus = "mismatch_known",
        items = emptyList(),
    )

    private fun itemsRow(idempotencyKey: String?): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.ReplaceItems,
        targetId = "expense:42",
        payloadJson = moshi().adapter(ExpenseItemReplaceRequestDto::class.java)
            .toJson(ExpenseItemReplaceRequestDto(expectedRowVersion = 0L, items = emptyList())),
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
        private val result: Result<ExpenseItemsResponseDto>,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        var lastIdempotencyKey: String? = null
            private set

        override suspend fun replaceExpenseItems(
            id: String,
            request: ExpenseItemReplaceRequestDto,
            idempotencyKey: String?,
        ): ExpenseItemsResponseDto {
            lastIdempotencyKey = idempotencyKey
            return result.getOrThrow()
        }
    }

    private fun dispatcherFor(stub: ApiService) = ReplaceItemsDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(ExpenseItemReplaceRequestDto::class.java),
    )

    @Test
    fun `dispatch replays the row's idempotency key and returns the parent row_version`() = runTest {
        val stub = Stub(Result.success(itemsResponse(rowVersion = 2L)))

        val result = dispatcherFor(stub).dispatch(itemsRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = 2L), result)
    }

    @Test
    fun `a row with no idempotency key fails loudly instead of silently dropping`() = runTest {
        val stub = Stub(Result.success(itemsResponse(rowVersion = 2L)))

        val result = dispatcherFor(stub).dispatch(itemsRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun `409 idempotency_key_in_progress is retried, not dropped`() = runTest {
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(itemsRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun `409 state_conflict still surfaces as a Conflict row`() = runTest {
        val body = """{"error":"state_conflict","message":"账单已被其它端修改"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(itemsRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
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
            retrofit2.Response.error<ExpenseItemsResponseDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
