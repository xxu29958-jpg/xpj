package com.ticketbox.data.remote.dto

import com.squareup.moshi.Moshi
import com.squareup.moshi.kotlin.reflect.KotlinJsonAdapterFactory
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertNull

class TagDtoContractTest {
    private val moshi = Moshi.Builder()
        .add(KotlinJsonAdapterFactory())
        .build()

    @Test
    fun tagManagementListParsesCurrentServerShape() {
        val dto = requireNotNull(
            moshi.adapter(TagManagementListDto::class.java).fromJson(
                """
                {
                  "items": [
                    { "public_id": "tag-1", "name": "出差", "usage_count": 3, "row_version": 2 },
                    { "public_id": "tag-2", "name": "差旅", "usage_count": 0, "row_version": 5 }
                  ]
                }
                """.trimIndent(),
            ),
        )
        assertEquals(2, dto.items.size)
        val first = dto.items.first()
        assertEquals("tag-1", first.publicId)
        assertEquals("出差", first.name)
        assertEquals(3, first.usageCount)
        assertEquals(2L, first.rowVersion)
        assertEquals(0, dto.items[1].usageCount) // orphan
    }

    @Test
    fun mutationRequestsSerializeWithOccTokensAndNoIdempotencyKey() {
        // 契约 7: every mutate body carries expected_row_version; no client key.
        assertEquals(
            """{"expected_row_version":2,"name":"餐饮"}""",
            moshi.adapter(TagRenameRequest::class.java)
                .toJson(TagRenameRequest(expectedRowVersion = 2L, name = "餐饮")),
        )
        assertEquals(
            """{"expected_row_version":2}""",
            moshi.adapter(TagDeleteRequest::class.java)
                .toJson(TagDeleteRequest(expectedRowVersion = 2L)),
        )
        assertEquals(
            """{"expected_row_version":2,"target_public_id":"tag-2","target_row_version":5}""",
            moshi.adapter(TagMergeRequest::class.java).toJson(
                TagMergeRequest(expectedRowVersion = 2L, targetPublicId = "tag-2", targetRowVersion = 5L),
            ),
        )
        assertEquals(
            """{"expected_row_version":7}""",
            moshi.adapter(TagUndoRequest::class.java)
                .toJson(TagUndoRequest(expectedRowVersion = 7L)),
        )
    }

    @Test
    fun mutationResponsesParseDeleteMergeAndUndoShapes() {
        val delete = requireNotNull(
            moshi.adapter(TagMutationDto::class.java).fromJson(
                """
                {
                  "mutation_public_id": "mut-1", "op": "delete",
                  "source_tag_public_id": "tag-1", "source_tag_row_version": 3,
                  "target_tag_public_id": null, "target_tag_row_version": null,
                  "affected_expense_count": 4
                }
                """.trimIndent(),
            ),
        )
        assertEquals("mut-1", delete.mutationPublicId)
        assertEquals(3L, delete.sourceTagRowVersion) // the undo token
        assertNull(delete.targetTagPublicId)
        assertEquals(4, delete.affectedExpenseCount)

        val undo = requireNotNull(
            moshi.adapter(TagUndoDto::class.java).fromJson(
                """{ "restored_tag_public_id": "tag-1", "restored_tag_row_version": 4, "applied": 3, "skipped": 1 }""",
            ),
        )
        assertEquals("tag-1", undo.restoredTagPublicId)
        assertEquals(3, undo.applied)
        assertEquals(1, undo.skipped)
    }
}
