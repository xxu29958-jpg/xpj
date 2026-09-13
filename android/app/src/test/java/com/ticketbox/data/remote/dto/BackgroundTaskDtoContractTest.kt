package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import com.ticketbox.data.repository.toDomain
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class BackgroundTaskDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun backgroundTaskDtoParsesFullShape() {
        val dto = requireNotNull(
            moshi.adapter(BackgroundTaskDto::class.java).fromJson(
                """
                {
                  "public_id": "task-abc",
                  "task_type": "csv_import",
                  "status": "running",
                  "progress_current": 2,
                  "progress_total": 3,
                  "progress_message": "importing rows 2/3",
                  "error_code": null,
                  "error_message": null,
                  "result_summary": null,
                  "created_at": "2026-05-31T12:00:00Z",
                  "started_at": "2026-05-31T12:00:05Z",
                  "completed_at": null,
                  "last_progress_at": "2026-05-31T12:00:10Z",
                  "cancellation_requested_at": null
                }
                """.trimIndent(),
            ),
        )

        assertEquals("task-abc", dto.publicId)
        assertEquals("csv_import", dto.taskType)
        assertEquals("running", dto.status)
        assertEquals(2, dto.progressCurrent)
        assertEquals(3, dto.progressTotal)
        assertEquals(
            "importing rows 2/3",
            dto.progressMessage,
        )
    }

    @Test
    fun backgroundTaskListResponseParsesEmptyAndPopulated() {
        val empty = requireNotNull(
            moshi.adapter(BackgroundTaskListResponseDto::class.java).fromJson("""{"items":[]}"""),
        )
        assertEquals(0, empty.items.size)

        val populated = requireNotNull(
            moshi.adapter(BackgroundTaskListResponseDto::class.java).fromJson(
                """
                {"items": [
                  {"public_id": "t1", "task_type": "csv_import", "status": "completed",
                   "progress_current": 0, "created_at": "2026-05-31T12:00:00Z"}
                ]}
                """.trimIndent(),
            ),
        )
        assertEquals(1, populated.items.size)
        assertEquals("t1", populated.items.first().publicId)
        assertEquals("completed", populated.items.first().status)
        assertNull(populated.items.first().toDomain().sourceExpenseId)
    }

    @Test
    fun recognitionTaskKeepsTheServerResolvedSourceThroughDomainMapping() {
        val dto = requireNotNull(moshi.adapter(BackgroundTaskDto::class.java).fromJson("""
            {"public_id":"recognition-1","task_type":"expense_enrichment","status":"failed",
            "source_expense_id":42,"created_at":"2026-09-07T12:00:00Z"}
        """.trimIndent()))
        assertEquals(42L, dto.toDomain().sourceExpenseId)
        assertNull(dto.copy(taskType = "unknown").toDomain().sourceExpenseId)
    }
}
