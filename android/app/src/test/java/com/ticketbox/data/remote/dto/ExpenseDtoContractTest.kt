package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertTrue

class ExpenseDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun uploadResponseDtoParsesCurrentServerShape() {
        val dto = requireNotNull(
            moshi.adapter(UploadResponseDto::class.java).fromJson(
                """
                {
                  "id": 1,
                  "public_id": "018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d",
                  "status": "pending",
                  "message": "uploaded",
                  "image_hash": "sha256",
                  "thumbnail_path": "uploads/owner/2026/05/thumbs/example.jpg",
                  "duplicate_status": "none",
                  "duplicate_of_id": null,
                  "upload_size_bytes": 348120,
                  "duration_ms": 86,
                  "timing_ms": {
                    "form_parse_ms": 8,
                    "file_save_ms": 18,
                    "db_create_ms": 24,
                    "total_ms": 86
                  }
                }
                """.trimIndent(),
            ),
        )

        assertEquals(1L, dto.id)
        assertEquals("018f4f90-2c20-7a2f-9d1c-6a6b81e69b2d", dto.publicId)
        assertEquals(348120L, dto.uploadSizeBytes)
        assertEquals(86L, dto.durationMs)
        assertEquals(24L, dto.timingMs?.get("db_create_ms"))
    }

    @Test
    fun notificationDraftRequestSerializesStructuredFieldsOnly() {
        val json = moshi.adapter(NotificationDraftRequestDto::class.java).toJson(
            NotificationDraftRequestDto(
                source = "wechat",
                originalCurrency = "CNY",
                originalAmount = "26.80",
                spentAt = "2026-05-13T10:05:00Z",
                merchant = "星巴克",
                category = "餐饮",
                expenseTime = "2026-05-13T10:05:00Z",
            ),
        )

        assertEquals(
            """{"source":"wechat","original_currency":"CNY","original_amount":"26.80","spent_at":"2026-05-13T10:05:00Z","merchant":"星巴克","category":"餐饮","expense_time":"2026-05-13T10:05:00Z"}""",
            json,
        )
        assertFalse(json.contains("raw_text"))
        assertFalse(json.contains("amount_cents"))
        assertFalse(json.contains("exchange_rate"))
    }

    @Test
    fun legacyMinimalExpensePayloadStillParsesRowVersionToken() {
        // Compatibility only: this intentionally sparse fixture documents that a
        // minimal legacy-ish payload still decodes row_version. The full ExpenseDto
        // field contract is enforced by OpenApiContractGateTest, which synthesizes
        // payloads from docs/architecture/openapi_contract.json instead of relying
        // on this hand-written fixture.
        val dto = requireNotNull(
            moshi.adapter(ExpenseDto::class.java).fromJson(
                """
                {
                  "id": 9,
                  "amount_cents": 1500,
                  "merchant": "星巴克",
                  "category": "餐饮",
                  "note": null,
                  "source": "Android截图",
                  "image_path": null,
                  "thumbnail_path": null,
                  "image_hash": null,
                  "raw_text": null,
                  "confidence": null,
                  "duplicate_status": "none",
                  "duplicate_of_id": null,
                  "duplicate_reason": null,
                  "tags": null,
                  "value_score": null,
                  "regret_score": null,
                  "status": "confirmed",
                  "expense_time": null,
                  "created_at": "2026-05-13T00:00:00Z",
                  "updated_at": "2026-05-13T00:05:00Z",
                  "row_version": 7,
                  "confirmed_at": "2026-05-13T00:05:00Z",
                  "rejected_at": null
                }
                """.trimIndent(),
            ),
        )

        assertEquals(9L, dto.id)
        assertEquals(7L, dto.rowVersion)
    }

    @Test
    fun updateRequestKeepsBlankMerchantAndTagsKeysAsExplicitClear() {
        // Clearing merchant/tags relies on submitting "" (NOT null): the
        // backend PATCH is exclude_unset and _clean_optional_text("") /
        // normalize_tags("") implement the clear. This pins the real Moshi
        // wire shape — the edit-screen unit tests run against a fake repo and
        // never serialize.
        val json = moshi.adapter(ExpenseUpdateRequest::class.java).toJson(
            ExpenseUpdateRequest(
                expectedRowVersion = 7L,
                merchant = "",
                category = "餐饮",
                note = "",
                expenseTime = null,
                tags = "",
                valueScore = null,
                regretScore = null,
            ),
        )

        assertTrue(json.contains("\"merchant\":\"\""))
        assertTrue(json.contains("\"tags\":\"\""))
        assertTrue(json.contains("\"expected_row_version\":7"))
    }

    @Test
    fun updateRequestOmitsNullMerchantAndTagsKeys() {
        // The dual of the explicit-clear contract: a null field must vanish
        // from the JSON entirely (Moshi omits null keys), which the backend's
        // exclude_unset reads as "unchanged". If a Moshi config change ever
        // started emitting literal nulls, tags:null would trip ADR-0042's
        // null-does-not-clear guard and merchant:null would clear fields the
        // user never touched.
        val json = moshi.adapter(ExpenseUpdateRequest::class.java).toJson(
            ExpenseUpdateRequest(
                expectedRowVersion = 7L,
                merchant = null,
                category = null,
                note = null,
                expenseTime = null,
                tags = null,
                valueScore = null,
                regretScore = null,
            ),
        )

        assertEquals("""{"expected_row_version":7}""", json)
    }
}
