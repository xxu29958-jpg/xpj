package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseRecognizeTextRequestDto
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
 * ADR-0042 Slice E-2: [RecognizeTextDispatcher] replay contract.
 *
 * Body-carrying like [ReplaceItemsDispatcherTest]: replays the row's intent-time
 * key, returns the parent expense's bumped ``row_version``, routes
 * ``idempotency_key_in_progress`` -> RETRY, keeps ``state_conflict`` -> Conflict,
 * fails loud on a keyless row. The EXTRA case vs the token-only RetryOcr template:
 * the pasted ``rawText`` must SURVIVE the ``copy(expectedRowVersion=…)`` the
 * dispatcher does before dispatch (only the token is overwritten).
 */
class RecognizeTextDispatcherTest {

    private fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private fun recognizedExpenseDto(rowVersion: Long): ExpenseDto = ExpenseDto(
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
            id: Long,
            request: ExpenseRecognizeTextRequestDto,
            idempotencyKey: String?,
        ): ExpenseDto {
            lastIdempotencyKey = idempotencyKey
            lastRequest = request
            return result.getOrThrow()
        }
    }

    private fun dispatcherFor(stub: ApiService) = RecognizeTextDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(ExpenseRecognizeTextRequestDto::class.java),
    )

    @Test
    fun `dispatch replays the row's idempotency key and returns the parent row_version`() = runTest {
        val stub = Stub(Result.success(recognizedExpenseDto(rowVersion = 8L)))

        val result = dispatcherFor(stub).dispatch(recognizeTextRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = 8L), result)
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
