package com.ticketbox.data.remote

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.remote.dto.StatusDto
import com.ticketbox.data.remote.dto.UploadResponseDto
import kotlin.test.Test
import kotlin.test.assertEquals

class ApiDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun statusDtoParsesRuleDeleteResponse() {
        val dto = requireNotNull(
            moshi.adapter(StatusDto::class.java).fromJson("""{"status":"ok"}"""),
        )

        assertEquals("ok", dto.status)
    }

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
}
