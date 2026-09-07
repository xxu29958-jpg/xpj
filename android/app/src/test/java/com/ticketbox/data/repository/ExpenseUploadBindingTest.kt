package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.UploadResponseDto
import kotlinx.coroutines.ExperimentalCoroutinesApi
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.MultipartBody
import okhttp3.ResponseBody.Companion.toResponseBody
import okio.Buffer
import retrofit2.HttpException
import retrofit2.Response
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertNull
import kotlin.test.assertTrue

@OptIn(ExperimentalCoroutinesApi::class)
internal class ExpenseUploadBindingTest {
    @Test
    fun preparedUploadCannotBindToAnotherOriginOrAccountWithTheSameLedgerId() = runTest {
        for (changeOrigin in listOf(true, false)) {
            var calls = 0
            val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
                override suspend fun uploadScreenshot(
                    file: MultipartBody.Part,
                    timezone: String?,
                    idempotencyKey: String?,
                ): UploadResponseDto {
                    assertNull(idempotencyKey)
                    calls += 1
                    return receipt()
                }
            }
            val session = TestSessionFixture().apply { saveToken("synthetic-session") }
            val repository = repository(api, session)
            val original = assertNotNull(repository.currentUploadBinding())
            val request = request(original)
            if (changeOrigin) {
                session.rebindToDifferentServerForFixture("https://different.test", "other-synthetic-session")
            } else {
                session.rebindAsDifferentAccountForFixture("另一成员", original.ledgerId, "原账本", "另一设备", "new-session")
            }

            val failure = repository.uploadScreenshot(request)

            assertEquals(original.ledgerId, repository.currentActiveLedgerId())
            assertTrue(failure.isFailure)
            assertEquals(0, calls)
            assertEquals(original, request.expectedBinding)
        }
    }

    @Test
    fun unchangedBindingCanRetryTheCapacityRefusalWithIdenticalBytes() = runTest {
        val bytes = mutableListOf<String>()
        val api = object : ApiService by FakeApiService(mutableListOf(), 0) {
            override suspend fun uploadScreenshot(
                file: MultipartBody.Part,
                timezone: String?,
                idempotencyKey: String?,
            ): UploadResponseDto {
                assertNull(idempotencyKey)
                val buffer = Buffer()
                file.body.writeTo(buffer)
                bytes += buffer.readUtf8()
                throw HttpException(Response.error<UploadResponseDto>(
                    503, """{"error":"enrichment_capacity_full","message":"服务正忙"}"""
                        .toResponseBody("application/json".toMediaTypeOrNull()),
                ))
            }
        }
        val repository = repository(api, TestSessionFixture().apply { saveToken("synthetic-session") })
        val request = request(assertNotNull(repository.currentUploadBinding()))

        val refused = repository.uploadScreenshot(request)
        val retried = repository.uploadScreenshot(request)

        assertEquals("enrichment_capacity_full", (refused.exceptionOrNull() as? RepositoryException)?.errorCode)
        assertEquals("enrichment_capacity_full", (retried.exceptionOrNull() as? RepositoryException)?.errorCode)
        assertEquals(listOf("original-image", "original-image"), bytes)
    }

    private fun repository(api: ApiService, session: TestSessionFixture) = expenseRepositoryFixture(
        expenseDao = FakeExpenseDao(),
        binding = testServerSessionBinding(
            apiClient = object : ApiServiceFactory {
                override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = api
            },
            settingsStore = FakeTicketboxSettingsStore(), tokenStore = session,
        ),
        deviceNameProvider = { "Synthetic Android" },
    )

    private fun request(binding: LogicalSessionBinding) = ScreenshotUploadRequest(
        fileName = "receipt.jpg", contentType = "image/jpeg", bytes = "original-image".encodeToByteArray(),
        expectedBinding = binding,
    )

    private fun receipt() = UploadResponseDto(
        id = 1L, publicId = "expense-1", enrichmentTaskPublicId = "task-1",
        status = "pending", message = "accepted", imageHash = "a".repeat(64),
        thumbnailPath = null, duplicateStatus = "none", duplicateOfId = null,
    )
}
