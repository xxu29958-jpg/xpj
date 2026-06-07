package com.ticketbox.data.repository

import com.ticketbox.data.remote.ApiService
import com.ticketbox.data.remote.ApiServiceFactory
import com.ticketbox.data.remote.dto.TagDetailDto
import com.ticketbox.data.remote.dto.TagRenameRequest
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
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * ADR-0043 review follow-up — TagRepository × real error carrier.
 *
 * Every `tag_conflict` token assertion in [com.ticketbox.viewmodel.TagManagementViewModelTest]
 * FABRICATES the [RepositoryException] (`failNext = RepositoryException(..., conflictTagPublicId = "b", ...)`),
 * so it never exercises the `HttpException → ErrorDto → RepositoryException` decode — exactly the seam the
 * round-2 P1 (flat-vs-nested `ErrorDto`) lived in. This drives a REAL [HttpException] through TagRepository
 * and asserts the conflict tokens survive the decode onto the exception the VM's 契约-5 prefill reads
 * ([[feedback_occ_test_token_from_rendered_carrier]]).
 */
class TagRepositoryConflictDecodeTest {

    @Test
    fun `rename 409 tag_conflict decodes the flat conflict tokens onto RepositoryException`() = runTest {
        // FLAT body: conflict_tag_* are TOP-LEVEL siblings of error/message (errors.py flattens
        // AppError.details onto the envelope) — the contract the round-2 P1 fix established.
        val body = """{"error":"tag_conflict","message":"标签名已被占用，请改用合并。",""" +
            """"conflict_tag_public_id":"b","conflict_tag_row_version":9}"""
        val repo = buildRepository(RenameConflictApiService(httpException(409, body)))

        val result = repo.renameTag(publicId = "a", expectedRowVersion = 1L, name = "差旅")

        assertTrue(result.isFailure)
        val ex = result.exceptionOrNull() as? RepositoryException
        assertNotNull(ex, "a 409 must surface as a RepositoryException")
        assertEquals("tag_conflict", ex.errorCode)
        assertEquals("b", ex.conflictTagPublicId) // decoded from the wire, not hand-placed
        assertEquals(9L, ex.conflictTagRowVersion)
    }

    @Test
    fun `nested details body yields null conflict tokens — pins the FLAT wire contract`() = runTest {
        // Negative control: if the backend ever regressed to nesting the tokens under "details",
        // the flat ErrorDto would decode them as null and the VM's merge prefill would go inert.
        // This documents that exact contract so such a regression is visible here, not in the wild.
        val body = """{"error":"tag_conflict","message":"x",""" +
            """"details":{"conflict_tag_public_id":"b","conflict_tag_row_version":9}}"""
        val repo = buildRepository(RenameConflictApiService(httpException(409, body)))

        val ex = repo.renameTag("a", 1L, "差旅").exceptionOrNull() as? RepositoryException

        assertNotNull(ex)
        assertEquals("tag_conflict", ex.errorCode)
        assertNull(ex.conflictTagPublicId) // nested → not seen by the flat DTO
        assertNull(ex.conflictTagRowVersion)
    }

    private fun buildRepository(api: ApiService): TagRepository = TagRepository(
        apiClient = TestApiServiceFactory(api),
        settingsStore = boundSettingsStore(), // server url + owner ledger seeded
        tokenStore = FakeSessionTokenStore().apply { saveToken("session-token") },
    )

    /** Wraps any [ApiService] into the factory TagRepository's [ApiServiceProvider] resolves through. */
    private class TestApiServiceFactory(private val service: ApiService) : ApiServiceFactory {
        override fun create(baseUrl: String, tokenProvider: () -> String?): ApiService = service
    }

    /** Throws on `renameTag`, delegates every other ApiService method to the shared fake. */
    private class RenameConflictApiService(
        private val error: Throwable,
        private val delegate: ApiService = FakeApiService(events = mutableListOf(), confirmedFailuresRemaining = 0),
    ) : ApiService by delegate {
        override suspend fun renameTag(publicId: String, request: TagRenameRequest): TagDetailDto = throw error
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
            retrofit2.Response.error<TagDetailDto>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
