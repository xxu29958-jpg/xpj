package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import com.ticketbox.data.remote.dto.ExpenseOffsetVoidRequestDto
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertIs

class ExpenseOffsetDispatchersTest {
    private val moshi = Moshi.Builder().build()

    private class Stub(
        private val createResult: Result<ExpenseFactBundleDto>,
        delegate: ApiService = FakeApiService(mutableListOf(), 0),
    ) : ApiService by delegate {
        var createId: String? = null
        var createRequest: ExpenseOffsetCreateRequestDto? = null
        var createKey: String? = null

        override suspend fun createExpenseOffset(
            id: String,
            request: ExpenseOffsetCreateRequestDto,
            idempotencyKey: String,
        ): ExpenseFactBundleDto {
            createId = id
            createRequest = request
            createKey = idempotencyKey
            return createResult.getOrThrow()
        }
    }

    @Test
    fun `create replay uses outbox OCC and key then publishes authoritative bundle`() = runTest {
        val bundle = expenseFactBundleDtoFixture(
            root = confirmedExpenseDtoFixture(rowVersion = 8),
        )
        val stub = Stub(Result.success(bundle))
        var published: Pair<String, ExpenseFactBundleDto>? = null
        val dispatcher = CreateExpenseOffsetDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi.adapter(ExpenseOffsetCreateRequestDto::class.java),
            publishBundle = { ledgerId, dto -> published = ledgerId to dto },
        )

        val result = dispatcher.dispatch(createRow())

        assertEquals("42", stub.createId)
        assertEquals("offset-key", stub.createKey)
        assertEquals(7L, stub.createRequest?.expectedRowVersion)
        assertEquals("owner" to bundle, published)
        assertEquals(DispatchResult.Success(newRowVersion = 8), result)
    }

    @Test
    fun `domain conflict remains visible instead of discarding queued intent`() = runTest {
        val stub = Stub(
            Result.failure(
                httpException(
                    409,
                    """{"error":"expense_offset_exceeds_remaining","message":"退款金额超过可退余额"}""",
                ),
            ),
        )
        val dispatcher = CreateExpenseOffsetDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi.adapter(ExpenseOffsetCreateRequestDto::class.java),
            publishBundle = { _, _ -> },
        )

        assertIs<DispatchResult.Failure>(dispatcher.dispatch(createRow()))
    }

    private fun createRow() = OutboxRow(
        id = 1,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.CreateExpenseOffset,
        targetId = expenseTargetId(42),
        payloadJson = moshi.adapter(ExpenseOffsetCreateRequestDto::class.java).toJson(
            ExpenseOffsetCreateRequestDto(
                kind = ExpenseOffsetKindDto.Refund,
                originalAmountMinor = 300,
                accountingDate = "2026-09-03",
                reason = "退款到账",
                expectedRowVersion = 0,
            ),
        ),
        expectedRowVersion = 7,
        status = PendingMutationStatus.InFlight,
        retryCount = 1,
        lastError = null,
        createdAt = "2026-09-03T04:00:00Z",
        attemptedAt = "2026-09-03T04:01:00Z",
        completedAt = null,
        idempotencyKey = "offset-key",
    )

    private fun httpException(code: Int, body: String): HttpException {
        val mediaType = "application/json".toMediaType()
        val raw = Response.Builder()
            .protocol(Protocol.HTTP_1_1)
            .request(Request.Builder().url("https://api.example.com/").build())
            .code(code)
            .message("test")
            .body(body.toResponseBody(mediaType))
            .build()
        return HttpException(
            retrofit2.Response.error<ExpenseFactBundleDto>(body.toResponseBody(mediaType), raw),
        )
    }
}
