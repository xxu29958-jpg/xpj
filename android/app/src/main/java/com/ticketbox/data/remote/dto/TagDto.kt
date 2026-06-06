package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

/**
 * ADR-0043 slice C — tag management DTOs (online-only mutate surface).
 *
 * Mirrors the `/api/tags` schemas: every mutation carries
 * `expected_row_version` (OCC) and NONE carries an `Idempotency-Key` header
 * (契约 7 — declaring one would route through the idempotency replay path).
 * Distinct from [TagsDto] (the read-only autocomplete name list).
 */
data class TagListItemDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val name: String,
    @param:Json(name = "usage_count")
    val usageCount: Int,
    @param:Json(name = "row_version")
    val rowVersion: Long,
)

data class TagManagementListDto(
    val items: List<TagListItemDto>,
)

data class TagRenameRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    val name: String,
)

data class TagDeleteRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

/** Merge source A (the `{publicId}` path tag) into target B; both tokens checked. */
data class TagMergeRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
    @param:Json(name = "target_public_id")
    val targetPublicId: String,
    @param:Json(name = "target_row_version")
    val targetRowVersion: Long,
)

data class TagUndoRequest(
    @param:Json(name = "expected_row_version")
    val expectedRowVersion: Long,
)

/** Rename response. */
data class TagDetailDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val name: String,
    @param:Json(name = "row_version")
    val rowVersion: Long,
)

/**
 * delete / merge response. `source_tag_row_version` is the undo token (the
 * soft-deleted source tag's new row_version, 契约 2 step ②).
 */
data class TagMutationDto(
    @param:Json(name = "mutation_public_id")
    val mutationPublicId: String,
    val op: String,
    @param:Json(name = "source_tag_public_id")
    val sourceTagPublicId: String,
    @param:Json(name = "source_tag_row_version")
    val sourceTagRowVersion: Long,
    @param:Json(name = "target_tag_public_id")
    val targetTagPublicId: String? = null,
    @param:Json(name = "target_tag_row_version")
    val targetTagRowVersion: Long? = null,
    @param:Json(name = "affected_expense_count")
    val affectedExpenseCount: Int,
)

data class TagUndoDto(
    @param:Json(name = "restored_tag_public_id")
    val restoredTagPublicId: String,
    @param:Json(name = "restored_tag_row_version")
    val restoredTagRowVersion: Long,
    val applied: Int,
    val skipped: Int,
)
