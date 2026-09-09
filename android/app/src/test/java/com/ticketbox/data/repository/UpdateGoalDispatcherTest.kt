package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.GoalDto
import com.ticketbox.data.remote.dto.GoalUpdateRequestDto
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
 * ADR-0042 Slice F: [UpdateGoalDispatcher] replay contract.
 *
 * Mirrors [UpdateCategoryRuleDispatcherTest]: replays the row's intent-time
 * key, routes ``idempotency_key_in_progress`` -> RETRY, keeps
 * ``state_conflict`` -> Conflict, surfaces ``422`` as a visible Failure, and
 * fails loud on a keyless row. The update response carries the goal's bumped
 * ``row_version``, surfaced as ``Success.newRowVersion``.
 */
class UpdateGoalDispatcherTest {

    private fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private fun updatedGoalDto(): GoalDto = GoalDto(
        publicId = "goal-1",
        ledgerId = "owner",
        name = "本月餐饮",
        goalType = "spending_limit",
        period = "monthly",
        month = "2026-05",
        category = "餐饮",
        targetAmountCents = 90000,
        spentAmountCents = 64000,
        remainingAmountCents = 26000,
        progressPercent = 71,
        progressState = "on_track",
        status = "active",
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-20T13:00:00.000Z",
        rowVersion = 2L,
        archivedAt = null,
        homeCurrencyCode = "JPY",
    )

    private fun goalRow(idempotencyKey: String?): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.UpdateGoal,
        targetId = "goal:goal-1",
        payloadJson = moshi().adapter(GoalUpdateRequestDto::class.java)
            .toJson(GoalUpdateRequestDto(expectedRowVersion = 1L, targetAmountCents = 90000, homeCurrencyCode = "JPY")),
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
        private val result: Result<GoalDto>,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        var lastIdempotencyKey: String? = null
            private set

        override suspend fun updateGoal(
            publicId: String,
            request: GoalUpdateRequestDto,
            idempotencyKey: String?,
            timezone: String?,
        ): GoalDto {
            lastIdempotencyKey = idempotencyKey
            return result.getOrThrow()
        }
    }

    private fun dispatcherFor(stub: ApiService) = UpdateGoalDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(GoalUpdateRequestDto::class.java),
        receiptAdapter = moshi().adapter(GoalDto::class.java),
    )

    @Test
    fun dispatchReplaysOriginalKeyAndStoresCanonicalReceipt() = runTest {
        val canonical = updatedGoalDto()
        val stub = Stub(Result.success(canonical))

        val result = dispatcherFor(stub).dispatch(goalRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastIdempotencyKey, "dispatcher must send the row's key")
        assertTrue(result is DispatchResult.Success)
        assertEquals(2L, result.newRowVersion)
        val receipt = result.receiptJson
        assertTrue(receipt != null, "the acknowledgement must survive Room reopen")
        assertEquals(canonical, moshi().adapter(GoalDto::class.java).fromJson(receipt))
    }

    @Test
    fun missingKeyFailsWithoutDiscarding() = runTest {
        val stub = Stub(Result.success(updatedGoalDto()))

        val result = dispatcherFor(stub).dispatch(goalRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun missingCurrencyOrWrongAcceptedReceiptCannotSettleTheOriginalEdit() = runTest {
        val row = goalRow("original-key")
        val legacy = row.copy(payloadJson = """{"expected_row_version":0,"target_amount_cents":90000}""")
        val stub = Stub(Result.success(updatedGoalDto()))
        assertTrue(dispatcherFor(stub).dispatch(legacy) is DispatchResult.Failure)
        assertEquals(null, stub.lastIdempotencyKey)
        listOf(updatedGoalDto().copy(homeCurrencyCode = "CNY"), updatedGoalDto().copy(rowVersion = 4),
            updatedGoalDto().copy(targetAmountCents = 1200)).forEach { wrong ->
            assertTrue(dispatcherFor(Stub(Result.success(wrong))).dispatch(row) is DispatchResult.Failure)
        }
        assertEquals("original-key", row.idempotencyKey)
    }

    @Test
    fun unreadableOriginalTargetRemainsFailed() = runTest {
        val stub = Stub(Result.success(updatedGoalDto()))
        val result = dispatcherFor(stub).dispatch(goalRow("original-key").copy(targetId = "goal:"))
        assertTrue(result is DispatchResult.Failure, "an unsent intent cannot become done: $result")
        assertEquals(null, stub.lastIdempotencyKey)
    }

    @Test
    fun inProgressKeyRetriesWithoutDiscarding() = runTest {
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(goalRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun stateConflictRemainsConflict() = runTest {
        val body = """{"error":"state_conflict","message":"目标已被其它端修改"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(goalRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
    }

    @Test
    fun invalidRequestRemainsVisibleFailure() = runTest {
        val body = """{"error":"idempotency_key_reused","message":"请求重复。"}"""
        val stub = Stub(Result.failure(httpException(422, body)))

        val result = dispatcherFor(stub).dispatch(goalRow(idempotencyKey = "key-abc"))

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
            retrofit2.Response.error<GoalDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
