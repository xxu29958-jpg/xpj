package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

class MerchantAliasDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun merchantAliasListParsesCurrentServerShapeAndSerializesPatch() {
        val dto = requireNotNull(
            moshi.adapter(MerchantAliasListDto::class.java).fromJson(
                """
                {
                  "items": [
                    {
                      "public_id": "alias-1",
                      "canonical_merchant": "星巴克",
                      "canonical_key": "星巴克",
                      "alias": "Starbucks",
                      "alias_key": "starbucks",
                      "enabled": true,
                      "created_at": "2026-05-13T00:00:00Z",
                      "updated_at": "2026-05-13T00:05:00Z"
                    }
                  ]
                }
                """.trimIndent(),
            ),
        )
        val patchJson = moshi.adapter(MerchantAliasRequest::class.java).toJson(
            MerchantAliasRequest(enabled = false),
        )
        // ADR-0038 PR-2e: PATCH/DELETE bodies carry expected_updated_at.
        val updateJson = moshi.adapter(MerchantAliasUpdateRequest::class.java).toJson(
            MerchantAliasUpdateRequest(
                expectedUpdatedAt = "2026-05-13T00:05:00Z",
                enabled = false,
            ),
        )
        val deleteJson = moshi.adapter(MerchantAliasDeleteRequest::class.java).toJson(
            MerchantAliasDeleteRequest(expectedUpdatedAt = "2026-05-13T00:05:00Z"),
        )

        val item = dto.items.single()
        assertEquals("alias-1", item.publicId)
        assertEquals("星巴克", item.canonicalMerchant)
        assertEquals("starbucks", item.aliasKey)
        assertEquals("""{"enabled":false}""", patchJson)
        assertEquals(
            """{"expected_updated_at":"2026-05-13T00:05:00Z","enabled":false}""",
            updateJson,
        )
        assertEquals(
            """{"expected_updated_at":"2026-05-13T00:05:00Z"}""",
            deleteJson,
        )
    }
}
