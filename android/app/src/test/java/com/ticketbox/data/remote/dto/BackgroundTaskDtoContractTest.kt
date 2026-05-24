package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals

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
                  "task_type": "v1_migration",
                  "status": "running",
                  "progress_current": 2,
                  "progress_total": 3,
                  "progress_message": "pre-v1.0 snapshot: ticketbox-pre-v1.0-20260601-120000.db",
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
        assertEquals("v1_migration", dto.taskType)
        assertEquals("running", dto.status)
        assertEquals(2, dto.progressCurrent)
        assertEquals(3, dto.progressTotal)
        assertEquals(
            "pre-v1.0 snapshot: ticketbox-pre-v1.0-20260601-120000.db",
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
    }
}
