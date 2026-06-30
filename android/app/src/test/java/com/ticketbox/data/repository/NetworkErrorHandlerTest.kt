package com.ticketbox.data.repository

import kotlinx.coroutines.test.runTest
import okhttp3.MediaType.Companion.toMediaTypeOrNull
import okhttp3.Protocol
import okhttp3.Request
import okhttp3.Response
import okhttp3.ResponseBody.Companion.toResponseBody
import retrofit2.HttpException
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull
import kotlin.test.assertTrue

/**
 * ADR-0043 review (P3): pins the NetworkErrorHandler → RepositoryException carrier
 * link. The backend flattens a `tag_conflict`'s colliding-tag identity onto the
 * error envelope's TOP level (errors.py `content.setdefault`), and the VM's
 * rename→merge steer (契约 5) reads those tokens off the RepositoryException. So
 * this asserts the FLAT tokens survive BOTH the JSON decode AND the HttpException →
 * RepositoryException mapping. ErrorDtoTest covers the DTO shape in isolation; the
 * earlier ViewModel tests fabricate RepositoryException directly and so never
 * exercised this decode/carrier path ([[feedback_occ_test_token_from_rendered_carrier]]).
 */
class NetworkErrorHandlerTest {
    private val handler = NetworkErrorHandler(boundSettingsStore(), context = "tag")

    private val tagConflictBody =
        """{"error":"tag_conflict","message":"已有同名标签，可改为合并。",""" +
            """"conflict_tag_public_id":"tag-xyz","conflict_tag_row_version":7}"""
    private val merchantConflictBody =
        """{"error":"state_conflict","message":"商家名已被占用。",""" +
            """"conflict_merchant_public_id":"merchant-xyz",""" +
            """"conflict_merchant_row_version":13,""" +
            """"conflict_merchant_display_name":"蓝瓶咖啡",""" +
            """"conflict_merchant_status":"active",""" +
            """"conflict_merchant_deleted":false,""" +
            """"conflict_alias_public_id":"alias-xyz",""" +
            """"conflict_alias_row_version":4,""" +
            """"conflict_alias_enabled":false,""" +
            """"conflict_alias_deleted":false}"""

    @Test
    fun parseErrorMessageKeepsFlatConflictTokens() {
        val parsed = handler.parseErrorMessage(409, tagConflictBody)
        assertEquals("tag_conflict", parsed.errorCode)
        assertEquals("tag-xyz", parsed.conflictTagPublicId)
        assertEquals(7L, parsed.conflictTagRowVersion) // JSON int → Long
    }

    @Test
    fun safeCallMapsHttpConflictToRepositoryExceptionWithTokens() = runTest {
        val result = handler.safeCall<Unit> { throw httpException(409, tagConflictBody) }

        assertTrue(result.isFailure)
        val ex = result.exceptionOrNull() as RepositoryException
        assertEquals("tag_conflict", ex.errorCode)
        assertEquals("tag-xyz", ex.conflictTagPublicId)
        assertEquals(7L, ex.conflictTagRowVersion)
    }

    @Test
    fun safeCallMapsHttpMerchantConflictToRepositoryExceptionWithTokens() = runTest {
        val result = handler.safeCall<Unit> { throw httpException(409, merchantConflictBody) }

        assertTrue(result.isFailure)
        val ex = result.exceptionOrNull() as RepositoryException
        assertEquals("state_conflict", ex.errorCode)
        assertEquals("merchant-xyz", ex.conflictMerchantPublicId)
        assertEquals(13L, ex.conflictMerchantRowVersion)
        assertEquals("蓝瓶咖啡", ex.conflictMerchantDisplayName)
        assertEquals("active", ex.conflictMerchantStatus)
        assertEquals(false, ex.conflictMerchantDeleted)
        assertEquals("alias-xyz", ex.conflictAliasPublicId)
        assertEquals(4L, ex.conflictAliasRowVersion)
        assertEquals(false, ex.conflictAliasEnabled)
        assertEquals(false, ex.conflictAliasDeleted)
    }

    @Test
    fun plainErrorCarriesNoConflictTokens() {
        val parsed = handler.parseErrorMessage(409, """{"error":"state_conflict","message":"x"}""")
        assertEquals("state_conflict", parsed.errorCode)
        assertNull(parsed.conflictTagPublicId)
        assertNull(parsed.conflictTagRowVersion)
        assertNull(parsed.conflictMerchantPublicId)
        assertNull(parsed.conflictMerchantRowVersion)
        assertNull(parsed.conflictAliasPublicId)
        assertNull(parsed.conflictAliasRowVersion)
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
            retrofit2.Response.error<Unit>(
                body.toResponseBody("application/json".toMediaTypeOrNull()),
                raw,
            ),
        )
    }
}
