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
 * ADR-0042 Slice F: [IncomePlanDispatcher] replay contract.
 *
 * Mirrors [UpdateGoalDispatcherTest] / [UpdateCategoryRuleDispatcherTest]:
 * replays the row's intent-time key, routes ``idempotency_key_in_progress`` ->
 * RETRY, keeps ``state_conflict`` -> Conflict, surfaces ``422`` as a visible
 * Failure, and fails loud on a keyless row. The update response carries the
 * plan's bumped ``row_version``, surfaced as ``Success.newRowVersion``.
 */
class IncomePlanDispatcherTest {

    private fun moshi(): Moshi {
        return Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
    }

    private fun updatedPlanDto(): IncomePlanDto {
        return IncomePlanDto(
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
            homeCurrencyCode = "CNY",
        )
    }

    private fun planRow(idempotencyKey: String?): OutboxRow {
        return OutboxRow(
            id = 1L,
            serverUrl = "https://api.example.com",
            ledgerId = "owner",
            type = PendingMutationType.UpdateIncomePlan,
            targetId = "income_plan:plan-1",
            payloadJson = moshi().adapter(IncomePlanSubmissionPayload::class.java)
                .toJson(IncomePlanSubmissionPayload(1, "plan-1", "工资", 1400000, "CNY", "test-session", "test-binding",
                    IncomePlanUpdateRequestDto(intentMonth = "2026-09", expectedRowVersion = 0L, amountCents = 1500000))),
            expectedRowVersion = 1L,
            status = PendingMutationStatus.InFlight,
            retryCount = 0,
            lastError = null,
            createdAt = "2026-05-20T12:00:00.000Z",
            attemptedAt = "2026-05-20T12:00:00.000Z",
            completedAt = null,
            idempotencyKey = idempotencyKey,
        )
    }

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

    private fun dispatcherFor(stub: ApiService): IncomePlanDispatcher {
        return IncomePlanDispatcher(
            type = PendingMutationType.UpdateIncomePlan,
            apiProvider = { stub },
            payloadAdapter = moshi().adapter(IncomePlanSubmissionPayload::class.java),
            receiptAdapter = moshi().adapter(IncomePlanDto::class.java),
        )
    }

    @Test
    fun dispatchReplaysOriginalIdempotencyKey() {
        runTest {
            val stub = Stub(Result.success(updatedPlanDto()))

            val result = dispatcherFor(stub).dispatch(planRow(idempotencyKey = "key-abc"))

            assertEquals("key-abc", stub.lastIdempotencyKey, "dispatcher must send the row's key")
            assertTrue(result is DispatchResult.Success)
            assertEquals(2L, result.newRowVersion)
            assertEquals(updatedPlanDto(), moshi().adapter(IncomePlanDto::class.java).fromJson(requireNotNull(result.receiptJson)))
        }
    }

    @Test
    fun keylessIntentRemainsVisible() {
        runTest {
            val stub = Stub(Result.success(updatedPlanDto()))

            val result = dispatcherFor(stub).dispatch(planRow(idempotencyKey = null))

            assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
        }
    }

    @Test
    fun differentMoneyCannotSettleOriginalIntent() {
        runTest {
            for (response in listOf(updatedPlanDto().copy(homeCurrencyCode = "JPY"),
                updatedPlanDto().copy(homeCurrencyCode = null), updatedPlanDto().copy(amountCents = 15000))) {
                val result = dispatcherFor(Stub(Result.success(response))).dispatch(planRow("original-key"))
                assertTrue(result is DispatchResult.Failure, "unverified money must remain recoverable: $result")
            }
        }
    }

    @Test
    fun inProgressResponseRemainsRetryable() {
        runTest {
            val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
            val stub = Stub(Result.failure(httpException(409, body)))

            val result = dispatcherFor(stub).dispatch(planRow(idempotencyKey = "key-abc"))

            assertTrue(
                result is DispatchResult.RetryableFailure,
                "in_progress must retry (not Discard/Conflict): $result",
            )
        }
    }

    @Test
    fun stateConflictRemainsVisible() {
        runTest {
            val body = """{"error":"state_conflict","message":"收入计划已被其它端修改"}"""
            val stub = Stub(Result.failure(httpException(409, body)))

            val result = dispatcherFor(stub).dispatch(planRow(idempotencyKey = "key-abc"))

            assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
        }
    }

    @Test
    fun invalidRequestRemainsVisible() {
        runTest {
            val body = """{"error":"idempotency_key_reused","message":"请求重复。"}"""
            val stub = Stub(Result.failure(httpException(422, body)))

            val result = dispatcherFor(stub).dispatch(planRow(idempotencyKey = "key-abc"))

            assertTrue(result is DispatchResult.Failure, "422 must be a visible Failure: $result")
        }
    }

    @Test
    fun missingOriginalResourceCannotAcknowledgeAnUnsentCommand() = runTest {
        val result = dispatcherFor(Stub(Result.failure(httpException(404,
            """{"error":"not_found","message":"Synthetic missing resource"}""")))).dispatch(planRow("original-key"))
        assertTrue(result is DispatchResult.Failure)
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
