package com.ticketbox.data.repository

import com.ticketbox.data.local.PendingMutationStatus
import com.ticketbox.data.local.PendingMutationType
import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.buildApiHttpClient
import com.ticketbox.data.remote.buildApiService
import com.ticketbox.data.remote.dto.ExpenseDto
import com.ticketbox.data.remote.dto.ExpenseStateTokenRequest
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Protocol
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFailsWith
import kotlin.test.assertTrue

internal class UndoExpenseDispatcherTest : ExpensePendingRepositoryOutboxTestBase() {
    private fun row(): OutboxRow = OutboxRow(
        id = 1L, serverUrl = "https://api.example.com", ledgerId = "owner", type = PendingMutationType.UndoExpense,
        targetId = "expense:42", payloadJson = """{"expected_row_version":0}""", expectedRowVersion = 1L,
        status = PendingMutationStatus.InFlight, retryCount = 0, lastError = null,
        createdAt = "2026-05-20T12:00:00.000Z", attemptedAt = null, completedAt = null, idempotencyKey = "original-undo-key",
    )

    private fun dispatcher(api: ApiService, publish: suspend (String, ExpenseDto) -> Unit = { _, _ -> }) =
        UndoExpenseDispatcher({ api }, moshi().adapter(ExpenseStateTokenRequest::class.java), publish)

    @Test
    fun `wire sends original key and token and retains historical confirmed acceptance when publication fails`() = runTest {
        val original = row()
        val response = successExpenseDto().copy(status = "confirmed", confirmedAt = "2026-05-01T12:00:00Z")
        var capturedPath: String? = null
        var capturedKey: String? = null
        var capturedBody: String? = null
        val client = buildApiHttpClient(null, { null }, { "owner" }, null, null)
            .newBuilder().addInterceptor { chain ->
                val request = chain.request()
                capturedPath = request.url.encodedPath
                capturedKey = request.header("Idempotency-Key")
                capturedBody = Buffer().also { request.body!!.writeTo(it) }.readUtf8()
                Response.Builder().request(request).protocol(Protocol.HTTP_1_1)
                    .code(200).message("OK")
                    .body(moshi().adapter(ExpenseDto::class.java).toJson(response)
                        .toResponseBody("application/json".toMediaType()))
                    .build()
            }.build()
        val api = buildApiService("https://api.example.com/", client)
        var publications = 0
        val result = dispatcher(api) { ledger, snapshot ->
            assertEquals("owner", ledger)
            assertEquals(response, snapshot)
            publications++
            throw IllegalStateException("cache unavailable")
        }.dispatch(original)
        assertEquals("/api/expenses/42/undo", capturedPath)
        assertEquals(original.idempotencyKey, capturedKey)
        assertEquals("""{"expected_row_version":1}""", capturedBody)
        assertEquals(1, publications)
        assertEquals(DispatchResult.Success(newRowVersion = 2L, cacheRefreshVersion = 2L,
            receiptJson = expenseAcceptanceReceiptJson(response)), result)
        assertEquals(response, expenseAcceptanceReceiptSnapshot(original.copy(status = PendingMutationStatus.Done,
            receiptJson = (result as DispatchResult.Success).receiptJson)))
    }

    @Test
    fun `successful pending restoration keeps its original accepted snapshot`() = runTest {
        val original = row()
        val response = successExpenseDto().copy(status = "pending")
        val api = object : ApiService by ApiServiceStub() {
            override suspend fun undoExpense(id: Long, request: ExpenseStateTokenRequest, idempotencyKey: String): ExpenseDto {
                assertEquals(42L, id)
                assertEquals(original.expectedRowVersion, request.expectedRowVersion)
                assertEquals(original.idempotencyKey, idempotencyKey)
                return response
            }
        }
        assertEquals(DispatchResult.Success(newRowVersion = response.rowVersion,
            receiptJson = expenseAcceptanceReceiptJson(response)), dispatcher(api).dispatch(original))
    }

    @Test
    fun `undo refusal and missing original receipt never become discarded success`() = runTest {
        val failures = listOf(
            httpException(404, """{"error":"expense_not_found","message":"已超过撤销窗口"}""") to "expense_not_found",
            httpException(409, """{"error":"expense_rejection_original_requires_review","message":"原回执无法核对"}""") to
                EXPENSE_REJECTION_ORIGINAL_REQUIRES_REVIEW,
        )
        for ((failure, message) in failures) {
            val api = object : ApiService by ApiServiceStub() {
                override suspend fun undoExpense(id: Long, request: ExpenseStateTokenRequest, idempotencyKey: String): ExpenseDto =
                    throw failure
            }
            assertEquals(DispatchResult.Failure(message), dispatcher(api).dispatch(row()))
        }
    }

    @Test
    fun `unverified response is not exposed and cancellation is preserved`() = runTest {
        val response = successExpenseDto().copy(status = "rejected")
        val api = object : ApiService by ApiServiceStub() {
            override suspend fun undoExpense(id: Long, request: ExpenseStateTokenRequest, idempotencyKey: String): ExpenseDto = response
        }
        assertEquals(DispatchResult.Failure(EXPENSE_REJECTION_ORIGINAL_REQUIRES_REVIEW), dispatcher(api).dispatch(row()))
        val cancelled = object : ApiService by ApiServiceStub() {
            override suspend fun undoExpense(id: Long, request: ExpenseStateTokenRequest, idempotencyKey: String): ExpenseDto =
                throw CancellationException("cancel original attempt")
        }
        assertFailsWith<CancellationException> { dispatcher(cancelled).dispatch(row()) }
        assertTrue(dispatcher(api).dispatch(row().copy(idempotencyKey = null)) is DispatchResult.Failure)
    }
}
