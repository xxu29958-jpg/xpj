package com.ticketbox.data.repository

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.dto.RecurringItemCreateRequestDto
import com.ticketbox.data.remote.dto.RecurringItemDto
import com.ticketbox.data.remote.dto.RecurringItemUpdateRequestDto
import com.ticketbox.data.remote.dto.addRecurringWireAdapters
import java.io.IOException
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

class RecurringItemDispatchersTest {
    private val moshi = Moshi.Builder()
        .addRecurringWireAdapters()
        .add(KotlinJsonAdapterFactory())
        .build()

    private fun itemDto(rowVersion: Long = 8): RecurringItemDto = RecurringItemDto(
        publicId = "recurring-1",
        ledgerId = "owner",
        merchant = "房租",
        merchantKey = "房租",
        frequency = "monthly",
        baselineAmountCents = 350000,
        lastAmountCents = 360000,
        occurrenceCount = 8,
        lastSeenAt = "2026-08-01T00:00:00Z",
        nextExpectedDate = "2026-09-01",
        status = "active",
        confidence = "high",
        source = "candidate",
        createdAt = "2026-01-01T00:00:00Z",
        updatedAt = "2026-08-30T00:00:00Z",
        rowVersion = rowVersion,
        pausedAt = null,
        archivedAt = null,
    )

    private class Stub(
        private val createResult: Result<RecurringItemDto>,
        private val updateResult: Result<RecurringItemDto> = createResult,
        delegate: ApiService = FakeApiService(mutableListOf(), 0),
    ) : ApiService by delegate {
        var createKey: String? = null
        var updateKey: String? = null
        var updateRequest: RecurringItemUpdateRequestDto? = null

        override suspend fun createRecurringItem(
            request: RecurringItemCreateRequestDto,
            idempotencyKey: String,
        ): RecurringItemDto {
            createKey = idempotencyKey
            return createResult.getOrThrow()
        }

        override suspend fun updateRecurringItem(
            publicId: String,
            request: RecurringItemUpdateRequestDto,
            idempotencyKey: String,
        ): RecurringItemDto {
            updateKey = idempotencyKey
            updateRequest = request
            return updateResult.getOrThrow()
        }
    }

    private fun createRow(key: String? = "create-key") = OutboxRow(
        id = 1,
        serverUrl = "https://api.example.com",
        ledgerId = "owner",
        type = PendingMutationType.CreateRecurringItem,
        targetId = "recurring_item_create:${key ?: "missing"}",
        payloadJson = moshi.adapter(RecurringItemCreateRequestDto::class.java).toJson(
            RecurringItemCreateRequestDto("房租", 350000, null),
        ),
        expectedRowVersion = 0,
        status = PendingMutationStatus.InFlight,
        retryCount = 1,
        lastError = null,
        createdAt = "2026-08-30T00:00:00Z",
        attemptedAt = "2026-08-30T00:00:00Z",
        completedAt = null,
        idempotencyKey = key,
    )

    private fun updateRow(key: String? = "update-key") = createRow(key).copy(
        type = PendingMutationType.UpdateRecurringItem,
        targetId = "recurring_item:recurring-1",
        payloadJson = moshi.adapter(RecurringItemUpdateRequestDto::class.java).toJson(
            RecurringItemUpdateRequestDto(expectedRowVersion = 0, baselineAmountCents = 355000),
        ),
        expectedRowVersion = 7,
    )

    @Test
    fun `create replay keeps original intent key`() = runTest {
        val stub = Stub(Result.success(itemDto()))

        val result = CreateRecurringItemDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi.adapter(RecurringItemCreateRequestDto::class.java),
        ).dispatch(createRow())

        assertEquals("create-key", stub.createKey)
        assertEquals(DispatchResult.Success(), result)
    }

    @Test
    fun `update replay uses row OCC token and returns fresh token`() = runTest {
        val stub = Stub(Result.success(itemDto()), Result.success(itemDto(rowVersion = 8)))

        val result = UpdateRecurringItemDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi.adapter(RecurringItemUpdateRequestDto::class.java),
        ).dispatch(updateRow())

        assertEquals("update-key", stub.updateKey)
        assertEquals(7, stub.updateRequest?.expectedRowVersion)
        assertEquals(DispatchResult.Success(newRowVersion = 8), result)
    }

    @Test
    fun `update state conflict remains user-resolvable conflict`() = runTest {
        val body = """{"error":"state_conflict","message":"固定支出已在另一端更新"}"""
        val stub = Stub(Result.success(itemDto()), Result.failure(httpException(409, body)))

        val result = UpdateRecurringItemDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi.adapter(RecurringItemUpdateRequestDto::class.java),
        ).dispatch(updateRow())

        assertTrue(result is DispatchResult.Conflict)
    }

    @Test
    fun `create duplicate remains visible instead of being silently discarded`() = runTest {
        val body = """{"error":"recurring_item_conflict","message":"这个商家已有固定支出"}"""
        val stub = Stub(Result.failure(httpException(409, body)))

        val result = CreateRecurringItemDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi.adapter(RecurringItemCreateRequestDto::class.java),
        ).dispatch(createRow())

        assertTrue(result is DispatchResult.Failure)
    }

    @Test
    fun `transient create IO stays retryable`() = runTest {
        val stub = Stub(Result.failure(IOException("offline")))

        val result = CreateRecurringItemDispatcher(
            apiProvider = { stub },
            payloadAdapter = moshi.adapter(RecurringItemCreateRequestDto::class.java),
        ).dispatch(createRow())

        assertTrue(result is DispatchResult.RetryableFailure)
    }

    private fun httpException(code: Int, body: String): HttpException {
        val mediaType = "application/json".toMediaTypeOrNull()
        val raw = Response.Builder()
            .protocol(Protocol.HTTP_1_1)
            .request(Request.Builder().url("https://api.example.com/").build())
            .code(code)
            .message("test")
            .body(body.toResponseBody(mediaType))
            .build()
        return HttpException(retrofit2.Response.error<RecurringItemDto>(body.toResponseBody(mediaType), raw))
    }
}
