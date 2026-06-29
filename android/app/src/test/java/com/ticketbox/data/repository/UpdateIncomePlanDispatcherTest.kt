package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.IncomePlanDto
import com.ticketbox.data.remote.dto.IncomePlanUpdateRequestDto
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
 * ADR-0042 Slice F: [UpdateIncomePlanDispatcher] replay contract.
 *
 * Mirrors [UpdateGoalDispatcherTest] / [UpdateCategoryRuleDispatcherTest]:
 * replays the row's intent-time key, routes ``idempotency_key_in_progress`` ->
 * RETRY, keeps ``state_conflict`` -> Conflict, surfaces ``422`` as a visible
 * Failure, and fails loud on a keyless row. The update response carries the
 * plan's bumped ``row_version``, surfaced as ``Success.newRowVersion``.
 */
class UpdateIncomePlanDispatcherTest {

    private fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private fun updatedPlanDto(): IncomePlanDto = IncomePlanDto(
        publicId = "plan-1",
        label = "工资",
        sourceType = "salary",
        frequency = "monthly",
        incomeMonth = null,
        amountCents = 1500000,
        payDay = 15,
        status = "active",
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-20T13:00:00.000Z",
        rowVersion = 2L,
        archivedAt = null,
    )

    private fun planRow(idempotencyKey: String?): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.UpdateIncomePlan,
        targetId = "income_plan:plan-1",
        payloadJson = moshi().adapter(IncomePlanUpdateRequestDto::class.java)
            .toJson(IncomePlanUpdateRequestDto(expectedRowVersion = 0L, amountCents = 1500000)),
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
        private val result: Result<IncomePlanDto>,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        var lastIdempotencyKey: String? = null
            private set

        override suspend fun updateIncomePlan(
            publicId: String,
            request: IncomePlanUpdateRequestDto,
            idempotencyKey: String?,
        ): IncomePlanDto {
            lastIdempotencyKey = idempotencyKey
            return result.getOrThrow()
        }
    }

    private fun dispatcherFor(stub: ApiService) = UpdateIncomePlanDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(IncomePlanUpdateRequestDto::class.java),
    )

    @Test
    fun `dispatch replays the row's idempotency key and returns the new row_version`() = runTest {
        val stub = Stub(Result.success(updatedPlanDto()))

        val result = dispatcherFor(stub).dispatch(planRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = 2L), result)
    }

    @Test
    fun `a row with no idempotency key fails loudly instead of silently dropping`() = runTest {
        val stub = Stub(Result.success(updatedPlanDto()))

        val result = dispatcherFor(stub).dispatch(planRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun `409 idempotency_key_in_progress is retried, not dropped`() = runTest {
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(planRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun `409 state_conflict still surfaces as a Conflict row`() = runTest {
        val body = """{"error":"state_conflict","message":"收入计划已被其它端修改"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(planRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
    }

    @Test
    fun `422 surfaces as a visible Failure, not a silent Discard`() = runTest {
        val body = """{"error":"idempotency_key_reused","message":"请求重复。"}"""
        val stub = Stub(Result.failure(httpException(422, body)))

        val result = dispatcherFor(stub).dispatch(planRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Failure, "422 must be a visible Failure: $result")
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
            retrofit2.Response.error<IncomePlanDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
