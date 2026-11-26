package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.ExpenseFactBundleDto
import com.ticketbox.data.remote.dto.ExpenseOffsetCreateRequestDto
import com.ticketbox.data.remote.dto.ExpenseOffsetKindDto
import com.ticketbox.data.remote.dto.ExpenseOffsetVoidRequestDto
import java.io.IOException
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertIs
import kotlin.test.assertNull
import kotlin.test.assertSame

class ExpenseOffsetDispatchersTest {
    private val moshi = Moshi.Builder().build()

    @Test
    fun missingRateRetainsTypedOriginalDateForManualRecovery() = runTest {
        val stub = Stub(Result.failure(httpException(409,
            """{"error":"exchange_rate_pending","message":"rate missing","currency_code":"USD","home_currency_code":"CNY","rate_date":"2026-09-03"}""")))
        val dispatcher = CreateExpenseOffsetDispatcher({ stub },
            moshi.adapter(ExpenseOffsetCreateRequestDto::class.java), { _, _ -> })
        val original = createRow()
        val result = assertIs<DispatchResult.Failure>(dispatcher.dispatch(original))
        val gap = requireNotNull(readCorrectionRateFailure(result.message))
        assertEquals("USD", gap.sourceCurrencyCode)
        assertEquals("CNY", gap.homeCurrencyCode)
        assertEquals("2026-09-03", gap.rateDate)
        assertEquals("offset-key", stub.createKey)
        assertEquals(7L, stub.createRequest?.expectedRowVersion)
    }

    @Test
    fun legacyNormalizedCreateRequiresReviewWithoutSending() = runTest {
        val stub = Stub(Result.success(expenseFactBundleDtoFixture()))
        val dispatcher = CreateExpenseOffsetDispatcher({ stub },
            moshi.adapter(ExpenseOffsetCreateRequestDto::class.java), { _, _ -> })
        val original = createRow().copy(payloadJson = createRow().payloadJson
            .replace("\"expected_row_version\":7", "\"expected_row_version\":0"))

        assertEquals(DispatchResult.Failure("offset_create_requires_review", definitelyRejected = true), dispatcher.dispatch(original))
        assertEquals(DispatchResult.Failure("offset_create_requires_review", definitelyRejected = true),
            dispatcher.dispatch(createRow().copy(expectedRowVersion = 8)))
        assertEquals(DispatchResult.Failure("offset_create_requires_review", definitelyRejected = true),
            dispatcher.dispatch(createRow().copy(payloadJson = "{")))
        assertEquals(null, stub.createRequest)
        assertEquals(null, stub.createKey)
    }

    @Test
    fun missingCreateTargetRequiresReviewInsteadOfClaimingDelivery() = runTest {
        val stub = Stub(Result.failure(httpException(404, """{"error":"expense_not_found"}""")))
        val dispatcher = CreateExpenseOffsetDispatcher({ stub },
            moshi.adapter(ExpenseOffsetCreateRequestDto::class.java), { _, _ -> })

        assertEquals(DispatchResult.Failure("offset_create_requires_review", definitelyRejected = true), dispatcher.dispatch(createRow()))
        assertEquals(7L, stub.createRequest?.expectedRowVersion)
        assertEquals("offset-key", stub.createKey)
    }

    private class Stub(
        private val createResult: Result<ExpenseFactBundleDto>,
        private val voidResult: Result<ExpenseFactBundleDto>? = null,
        delegate: ApiService = FakeApiService(mutableListOf(), 0),
    ) : ApiService by delegate {
        var createId: String? = null
        var createRequest: ExpenseOffsetCreateRequestDto? = null
        var createKey: String? = null
        var voidId: String? = null
        var voidOffsetPublicId: String? = null
        var voidRequest: ExpenseOffsetVoidRequestDto? = null
        var voidKey: String? = null

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

        override suspend fun voidExpenseOffset(
            id: String,
            offsetPublicId: String,
            request: ExpenseOffsetVoidRequestDto,
            idempotencyKey: String,
        ): ExpenseFactBundleDto {
            voidId = id
            voidOffsetPublicId = offsetPublicId
            voidRequest = request
            voidKey = idempotencyKey
            return requireNotNull(voidResult).getOrThrow()
        }
    }

    @Test
    fun `create replay sends the original body and key then publishes authoritative bundle`() = runTest {
        val bundle = expenseFactBundleDtoFixture(
            root = confirmedExpenseDtoFixture(ConfirmedExpenseFixture(rowVersion = 8)),
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
        assertEquals(moshi.adapter(ExpenseOffsetCreateRequestDto::class.java).fromJson(createRow().payloadJson), stub.createRequest)
        assertEquals("owner" to bundle, published)
        assertEquals(DispatchResult.Success(newRowVersion = 8), result)
    }

    @Test
    fun createFundAccountNotFoundPreservesAccountErrorInsteadOfTargetReview() = runTest {
        val body = """{"error":"fund_account_not_found","message":"这个资金账户不存在或你没有访问权限。"}"""
        val stub = Stub(Result.failure(httpException(404, body)))
        val dispatcher = CreateExpenseOffsetDispatcher({ stub },
            moshi.adapter(ExpenseOffsetCreateRequestDto::class.java), { _, _ -> })

        assertEquals(
            DispatchResult.Failure("这个资金账户不存在或你没有访问权限。", definitelyRejected = true),
            dispatcher.dispatch(createRow()),
        )
    }

    @Test
    fun `domain conflict remains visible instead of discarding queued intent`() = runTest {
        val stub = Stub(
            Result.failure(
                httpException(
                    409,
                    """{"error":"expense_refund_exceeds_remaining","message":"退款金额超过可退余额"}""",
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

    @Test
    fun `void replay keeps offset OCC but returns the bumped root token`() = runTest {
        val bundle = expenseFactBundleDtoFixture(
            root = confirmedExpenseDtoFixture(ConfirmedExpenseFixture(rowVersion = 8)),
            activeOffsets = emptyList(),
        )
        val stub = Stub(Result.failure(AssertionError("create not expected")), Result.success(bundle))
        var published: Pair<String, ExpenseFactBundleDto>? = null
        val dispatcher = VoidExpenseOffsetDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi.adapter(ExpenseOffsetVoidOutboxPayload::class.java),
            publishBundle = { ledgerId, dto -> published = ledgerId to dto },
        )

        val result = dispatcher.dispatch(voidRow())

        assertEquals("42", stub.voidId)
        assertEquals("refund-1", stub.voidOffsetPublicId)
        assertEquals(3L, stub.voidRequest?.expectedRowVersion)
        assertEquals("撤销误记", stub.voidRequest?.voidReason)
        assertEquals("void-key", stub.voidKey)
        assertEquals("owner" to bundle, published)
        assertEquals(DispatchResult.Success(newRowVersion = 8), result)
    }

    @Test
    fun acceptedCreateWithFailedCacheKeepsItsRootRefreshReceiptAndOriginalCommand() = runTest {
        val bundle = expenseFactBundleDtoFixture(
            root = confirmedExpenseDtoFixture(ConfirmedExpenseFixture(rowVersion = 8)))
        val stub = Stub(Result.success(bundle))
        var failure: Exception = IllegalStateException("Room unavailable")
        var published: Pair<String, ExpenseFactBundleDto>? = null
        val dispatcher = CreateExpenseOffsetDispatcher({ stub },
            moshi.adapter(ExpenseOffsetCreateRequestDto::class.java), { ledgerId, response ->
                published = ledgerId to response
                throw failure
            })
        val original = createRow()
        for (cacheFailure in listOf(IllegalStateException("Room unavailable"), IOException("cache IO"))) {
            failure = cacheFailure
            assertEquals(DispatchResult.Success(newRowVersion = 8, cacheRefreshVersion = 8,
                receiptJson = """{"expenseId":9}"""), dispatcher.dispatch(original))
            assertEquals("owner" to bundle, published)
            assertEquals("42", stub.createId)
            assertEquals("offset-key", stub.createKey)
            assertEquals(moshi.adapter(ExpenseOffsetCreateRequestDto::class.java).fromJson(original.payloadJson), stub.createRequest)
            assertEquals(7L, stub.createRequest?.expectedRowVersion)
        }
        val cancelled = CancellationException("binding changed")
        failure = cancelled
        assertSame(cancelled, assertFailsWith<CancellationException> { dispatcher.dispatch(original) })
    }

    @Test
    fun acceptedVoidWithFailedCacheKeepsItsRootRefreshReceiptAndOffsetVersion() = runTest {
        val bundle = expenseFactBundleDtoFixture(
            root = confirmedExpenseDtoFixture(ConfirmedExpenseFixture(rowVersion = 8)), activeOffsets = emptyList())
        val stub = Stub(Result.failure(AssertionError("create not expected")), Result.success(bundle))
        var failure: Exception = IllegalStateException("Room unavailable")
        var published: Pair<String, ExpenseFactBundleDto>? = null
        val dispatcher = VoidExpenseOffsetDispatcher({ stub },
            moshi.adapter(ExpenseOffsetVoidOutboxPayload::class.java), { ledgerId, response ->
                published = ledgerId to response
                throw failure
            })
        val original = voidRow()
        for (cacheFailure in listOf(IllegalStateException("Room unavailable"), IOException("cache IO"))) {
            failure = cacheFailure
            assertEquals(DispatchResult.Success(newRowVersion = 8, cacheRefreshVersion = 8,
                receiptJson = """{"expenseId":9}"""), dispatcher.dispatch(original))
            assertEquals("owner" to bundle, published)
            assertEquals("42", stub.voidId)
            assertEquals("refund-1", stub.voidOffsetPublicId)
            assertEquals("void-key", stub.voidKey)
            assertEquals(ExpenseOffsetVoidRequestDto("撤销误记", 3), stub.voidRequest)
        }
        val cancelled = CancellationException("binding changed")
        failure = cancelled
        assertSame(cancelled, assertFailsWith<CancellationException> { dispatcher.dispatch(original) })
    }

    @Test
    fun voidAnomalous404StaysVisibleFailureWhileAlreadyVoided409Discards() = runTest {
        val adapter = moshi.adapter(ExpenseOffsetVoidOutboxPayload::class.java)
        for ((body, expectedMessage) in listOf(
            """{"error":"fund_account_not_found","message":"这个资金账户不存在或你没有访问权限。"}""" to "这个资金账户不存在或你没有访问权限。",
            """{"error":"expense_offset_not_found","message":"没有找到这条退款或冲销记录。"}""" to "没有找到这条退款或冲销记录。",
            """{"error":"expense_not_found","message":"账单不存在。"}""" to "账单不存在。",
            """{"error":"route_not_found","message":"没有找到这个功能入口。"}""" to "账本版本过旧，请重启电脑上的小票夹后再试。",
        )) {
            val stub = Stub(Result.failure(AssertionError("create not expected")), Result.failure(httpException(404, body)))
            val dispatcher = VoidExpenseOffsetDispatcher({ stub }, adapter, { _, _ -> })
            assertEquals(DispatchResult.Failure(expectedMessage, definitelyRejected = true), dispatcher.dispatch(voidRow()))
        }

        val alreadyVoided = Stub(
            Result.failure(AssertionError("create not expected")),
            Result.failure(httpException(409, """{"error":"expense_offset_not_active","message":"这条退款或冲销记录已经撤销。"}""")),
        )
        assertEquals(
            DispatchResult.Discarded("这条退款或冲销记录已经撤销。"),
            VoidExpenseOffsetDispatcher({ alreadyVoided }, adapter, { _, _ -> }).dispatch(voidRow()),
        )

        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao)
        val rowId = outbox.enqueue(
            type = PendingMutationType.VoidExpenseOffset,
            targetId = expenseTargetId(42),
            payloadJson = voidRow().payloadJson,
            expectedRowVersion = 3L,
            idempotencyKey = "void-key-404",
        )
        val stub404 = Stub(
            Result.failure(AssertionError("create not expected")),
            Result.failure(httpException(404, """{"error":"fund_account_not_found","message":"这个资金账户不存在或你没有访问权限。"}""")),
        )
        dao.runnableBatches += listOf(rowId)
        val summary = OutboxDrainEngine(outbox, listOf(VoidExpenseOffsetDispatcher({ stub404 }, adapter, { _, _ -> }))).drainOnce()
        assertEquals(1, summary.failures)
        assertEquals(0, summary.done)
        assertEquals(0, summary.discarded)
        assertEquals(PendingMutationStatus.Failed.wireValue, dao.rows.getValue(rowId).status)
        assertNull(dao.rows.getValue(rowId).completedAt)
    }

    @Test
    fun offset409ClassifiesStrictlyByErrorCodeNotMessageSubstring() = runTest {
        val adapter = moshi.adapter(ExpenseOffsetVoidOutboxPayload::class.java)
        for (spoofedMessage in listOf(
            "expense_offset_not_active",
            "state_conflict / idempotency_key_in_progress",
        )) {
            val body = """{"error":"expense_not_confirmed","message":"$spoofedMessage"}"""
            val stub = Stub(Result.failure(AssertionError("create not expected")), Result.failure(httpException(409, body)))
            val result = VoidExpenseOffsetDispatcher({ stub }, adapter, { _, _ -> }).dispatch(voidRow())
            assertEquals(DispatchResult.Failure(spoofedMessage), result)
        }
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
                expectedRowVersion = 7,
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

    private fun voidRow() = createRow().copy(
        type = PendingMutationType.VoidExpenseOffset,
        targetId = expenseTargetId(42),
        payloadJson = moshi.adapter(ExpenseOffsetVoidOutboxPayload::class.java).toJson(
            ExpenseOffsetVoidOutboxPayload(offsetPublicId = "refund-1", voidReason = "撤销误记"),
        ),
        expectedRowVersion = 3,
        idempotencyKey = "void-key",
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
