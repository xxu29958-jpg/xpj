package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.MerchantCatalogDto
import com.ticketbox.data.remote.dto.MerchantCatalogUpdateRequest
import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNotNull
import kotlin.test.assertTrue

class MerchantRepositoryConflictDecodeTest {

    @Test
    fun `rename 409 state_conflict decodes flat merchant conflict fields`() = runTest {
        val body = """{"error":"state_conflict","message":"商家名已被占用。",""" +
            """"conflict_merchant_public_id":"target",""" +
            """"conflict_merchant_row_version":9,""" +
            """"conflict_merchant_display_name":"蓝瓶咖啡",""" +
            """"conflict_merchant_status":"active",""" +
            """"conflict_merchant_deleted":false}"""
        val repo = MerchantRepository(
            apiClient = TestApiServiceFactory(UpdateConflictApiService(httpException(409, body))),
            settingsStore = boundSettingsStore(),
            tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
        )

        val result = repo.updateMerchantCatalog(
            publicId = "source",
            expectedRowVersion = 1L,
            displayName = "蓝瓶咖啡",
        )

        assertTrue(result.isFailure)
        val ex = result.exceptionOrNull() as? RepositoryException
        assertNotNull(ex)
        assertEquals("state_conflict", ex.errorCode)
        assertEquals("target", ex.conflictMerchantPublicId)
        assertEquals(9L, ex.conflictMerchantRowVersion)
        assertEquals("蓝瓶咖啡", ex.conflictMerchantDisplayName)
        assertEquals("active", ex.conflictMerchantStatus)
        assertEquals(false, ex.conflictMerchantDeleted)
    }

    private class TestApiServiceFactory(private val service: ApiService) : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
    }

    private class UpdateConflictApiService(
        private val error: Throwable,
        private val delegate: ApiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0),
    ) : ApiService by delegate {
        override suspend fun updateMerchantCatalog(
            publicId: String,
            request: MerchantCatalogUpdateRequest,
            idempotencyKey: String?,
        ): MerchantCatalogDto = throw error
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
            retrofit2.Response.error<MerchantCatalogDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
