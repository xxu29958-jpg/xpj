package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

/**
 * ADR-0043 review: pins ErrorDto against the REAL flat wire shape. The backend
 * flattens AppError.details onto the error envelope's top level (errors.py), so a
 * regression to a nested model — which silently nulls the tag-conflict tokens and
 * makes the rename→merge fresh-token steer inert — fails here at decode time.
 */
class ErrorDtoTest {
    private val adapter = Moshi.Builder().add(KotlinJsonAdapterFactory()).build()
        .adapter(ErrorDto::class.java)

    @Test
    fun decodesFlatTagConflictTokens() {
        val dto = adapter.fromJson(
            """{"error":"tag_conflict","message":"标签名已被占用，请改用合并。",""" +
                """"conflict_tag_public_id":"tag-abc","conflict_tag_row_version":9}""",
        )!!
        assertEquals("tag_conflict", dto.error)
        assertEquals("tag-abc", dto.conflictTagPublicId)
        assertEquals(9L, dto.conflictTagRowVersion) // JSON int → Long
    }

    @Test
    fun decodesFlatMerchantConflictTokens() {
        val dto = adapter.fromJson(
            """{"error":"state_conflict","message":"商家名已被占用。",""" +
                """"conflict_merchant_public_id":"merchant-abc",""" +
                """"conflict_merchant_row_version":11,""" +
                """"conflict_merchant_display_name":"蓝瓶咖啡",""" +
                """"conflict_merchant_status":"active",""" +
                """"conflict_merchant_deleted":false,""" +
                """"conflict_alias_public_id":"alias-abc",""" +
                """"conflict_alias_row_version":5,""" +
                """"conflict_alias_enabled":true,""" +
                """"conflict_alias_deleted":false}""",
        )!!
        assertEquals("state_conflict", dto.error)
        assertEquals("merchant-abc", dto.conflictMerchantPublicId)
        assertEquals(11L, dto.conflictMerchantRowVersion)
        assertEquals("蓝瓶咖啡", dto.conflictMerchantDisplayName)
        assertEquals("active", dto.conflictMerchantStatus)
        assertEquals(false, dto.conflictMerchantDeleted)
        assertEquals("alias-abc", dto.conflictAliasPublicId)
        assertEquals(5L, dto.conflictAliasRowVersion)
        assertEquals(true, dto.conflictAliasEnabled)
        assertEquals(false, dto.conflictAliasDeleted)
    }

    @Test
    fun plainErrorLeavesConflictTokensNull() {
        val dto = adapter.fromJson("""{"error":"state_conflict","message":"x"}""")!!
        assertEquals("state_conflict", dto.error)
        assertNull(dto.conflictTagPublicId)
        assertNull(dto.conflictTagRowVersion)
        assertNull(dto.conflictMerchantPublicId)
        assertNull(dto.conflictMerchantRowVersion)
        assertNull(dto.conflictAliasPublicId)
        assertNull(dto.conflictAliasRowVersion)
    }
}
