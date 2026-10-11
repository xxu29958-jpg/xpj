package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.MerchantAliasDto
import com.ticketbox.data.remote.dto.MerchantAliasUpdateRequest
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
 * ADR-0042 Slice D-2: [UpdateMerchantAliasDispatcher] replay contract.
 *
 * Mirrors [PatchExpenseDispatcherTest]: replays the row's intent-time key,
 * routes ``idempotency_key_in_progress`` -> RETRY, keeps ``state_conflict`` ->
 * Conflict, fails loud on a keyless row. The update response carries the alias'
 * bumped ``row_version``, surfaced as ``Success.newRowVersion``.
 */
class UpdateMerchantAliasDispatcherTest {

    private fun moshi(): Moshi = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()

    private fun updatedAliasDto(): MerchantAliasDto = MerchantAliasDto(
        publicId = "alias-public-1",
        canonicalMerchant = "标准商家",
        canonicalKey = "标准商家",
        alias = "新别名",
        aliasKey = "新别名",
        enabled = true,
        createdAt = "2026-05-01T00:00:00Z",
        updatedAt = "2026-05-20T13:00:00.000Z",
        rowVersion = 2L,
    )

    private fun aliasRow(idempotencyKey: String?): OutboxRow = OutboxRow(
        id = 1L,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.UpdateMerchantAlias,
        targetId = "merchant_alias:alias-public-1",
        payloadJson = moshi().adapter(MerchantAliasUpdateRequest::class.java)
            .toJson(MerchantAliasUpdateRequest(expectedRowVersion = 0L, alias = "新别名")),
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
        private val result: Result<MerchantAliasDto>,
        private val delegate: ApiService = FakeApiService(
            events = mutableListOf(),
            confirmedFailuresRemaining = 0,
        ),
    ) : ApiService by delegate {
        var lastIdempotencyKey: String? = null
            private set

        override suspend fun updateMerchantAlias(
            publicId: String,
            request: MerchantAliasUpdateRequest,
            idempotencyKey: String?,
        ): MerchantAliasDto {
            lastIdempotencyKey = idempotencyKey
            return result.getOrThrow()
        }
    }

    private fun dispatcherFor(stub: ApiService) = UpdateMerchantAliasDispatcher(
        apiProvider = { stub },
        payloadAdapter = moshi().adapter(MerchantAliasUpdateRequest::class.java),
    )

    @Test
    fun `dispatch replays the row's idempotency key and returns the new row_version`() = runTest {
        val stub = Stub(Result.success(updatedAliasDto()))

        val result = dispatcherFor(stub).dispatch(aliasRow(idempotencyKey = "key-abc"))

        assertEquals("key-abc", stub.lastIdempotencyKey, "dispatcher must send the row's key")
        assertEquals(DispatchResult.Success(newRowVersion = 2L), result)
    }

    @Test
    fun `a row with no idempotency key fails loudly instead of silently dropping`() = runTest {
        val stub = Stub(Result.success(updatedAliasDto()))

        val result = dispatcherFor(stub).dispatch(aliasRow(idempotencyKey = null))

        assertTrue(result is DispatchResult.Failure, "null-key row must FAIL visibly: $result")
    }

    @Test
    fun `409 idempotency_key_in_progress is retried, not dropped`() = runTest {
        val body = """{"error":"idempotency_key_in_progress","message":"操作正在处理中，请稍后再试。"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(aliasRow(idempotencyKey = "key-abc"))

        assertTrue(
            result is DispatchResult.RetryableFailure,
            "in_progress must retry (not Discard/Conflict): $result",
        )
    }

    @Test
    fun `409 state_conflict still surfaces as a Conflict row`() = runTest {
        val body = """{"error":"state_conflict","message":"别名已被其它端修改"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = dispatcherFor(stub).dispatch(aliasRow(idempotencyKey = "key-abc"))

        assertTrue(result is DispatchResult.Conflict, "state_conflict must stay Conflict: $result")
    }

    @Test
    fun `a newer peer version or another object cannot settle the original or rebase its successor`() = runTest {
        for (receipt in listOf(updatedAliasDto().copy(rowVersion = 3L), updatedAliasDto().copy(publicId = "peer-alias"))) {
            val dao = FakePendingMutationDao()
            val outbox = testOutboxRepository(dao = dao)
            val original = aliasRow("original-key")
            val firstId = outbox.enqueue(original.type, original.targetId, original.payloadJson, 1L,
                idempotencyKey = "original-key")
            val nextId = outbox.enqueue(original.type, original.targetId, original.payloadJson, 1L,
                idempotencyKey = "following-key")
            val summary = OutboxDrainEngine(outbox, listOf(dispatcherFor(Stub(Result.success(receipt))))).drainOnce()

            assertEquals(0, summary.done)
            assertEquals(1, summary.failures)
            assertEquals(PendingMutationStatus.Failed.wireValue, dao.rows.getValue(firstId).status)
            assertEquals(PendingMutationStatus.Pending.wireValue, dao.rows.getValue(nextId).status)
            assertEquals(1L, dao.rows.getValue(nextId).expectedRowVersion)
            assertEquals(original.payloadJson, dao.rows.getValue(nextId).payload)
            assertEquals("following-key", dao.rows.getValue(nextId).idempotencyKey)
        }
    }

    @Test
    fun `the accepted version settles the original while a peer edit still conflicts with the successor`() = runTest {
        val dao = FakePendingMutationDao()
        val outbox = testOutboxRepository(dao = dao)
        val original = aliasRow("original-key")
        val receivedVersions = mutableListOf<Long>()
        val api = object : ApiService by FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0) {
            override suspend fun updateMerchantAlias(
                publicId: String, request: MerchantAliasUpdateRequest, idempotencyKey: String?,
            ): MerchantAliasDto {
                receivedVersions += request.expectedRowVersion
                if (idempotencyKey == "original-key") return updatedAliasDto()
                if (request.expectedRowVersion != 3L) {
                    throw httpException(409, """{"error":"state_conflict","message":"他端已修改别名"}""")
                }
                error("The peer's version must never authorize this unsent successor")
            }
        }
        val firstId = outbox.enqueue(original.type, original.targetId, original.payloadJson, 1L,
            idempotencyKey = "original-key")
        val nextId = outbox.enqueue(original.type, original.targetId, original.payloadJson, 1L,
            idempotencyKey = "following-key")

        val summary = OutboxDrainEngine(outbox, listOf(dispatcherFor(api))).drainOnce()

        assertEquals(listOf(1L, 2L), receivedVersions)
        assertEquals(1, summary.done)
        assertEquals(1, summary.conflicts)
        assertEquals(PendingMutationStatus.Done.wireValue, dao.rows.getValue(firstId).status)
        assertEquals(PendingMutationStatus.Conflict.wireValue, dao.rows.getValue(nextId).status)
        assertEquals("following-key", dao.rows.getValue(nextId).idempotencyKey)
        assertEquals(original.payloadJson, dao.rows.getValue(nextId).payload)
    }

    @Test
    fun `a historical acceptance without its receipt remains unresolved`() = runTest {
        val response = """{"error":"merchant_alias_original_requires_review","message":"原修改已接受，请核对商家别名"}"""
        val result = dispatcherFor(Stub(Result.failure(httpException(409, response))))
            .dispatch(aliasRow("original-key"))

        assertTrue(result is DispatchResult.Failure)
        assertTrue(result.blocksFollowing)
        assertEquals(false, result.definitelyRejected)
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
            retrofit2.Response.error<MerchantAliasDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
