package com.ticketbox.data.remote.dto

import com.squareup.moshi.Json

data class CategoryRuleDto(
    val id: Long,
    val keyword: String,
    val category: String,
    val enabled: Boolean,
    val priority: Int,
    @param:Json(name = "amount_min_cents")
    val amountMinCents: Long? = null,
    @param:Json(name = "amount_max_cents")
    val amountMaxCents: Long? = null,
    @param:Json(name = "source_contains")
    val sourceContains: String? = null,
    @param:Json(name = "tag_contains")
    val tagContains: String? = null,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "updated_at")
    val updatedAt: String,
)

data class CategoryRuleRequest(
    val keyword: String?,
    val category: String?,
    val enabled: Boolean?,
    val priority: Int?,
    @param:Json(name = "amount_min_cents")
    val amountMinCents: Long? = null,
    @param:Json(name = "amount_max_cents")
    val amountMaxCents: Long? = null,
    @param:Json(name = "source_contains")
    val sourceContains: String? = null,
    @param:Json(name = "tag_contains")
    val tagContains: String? = null,
)

/**
 * ADR-0038 PR-1: PATCH /api/rules/categories/{id} body carries the
 * client's last-seen ``updated_at`` so a peer edit between the read
 * and this PATCH surfaces as 409 ``state_conflict`` instead of a
 * silent overwrite.
 */
data class CategoryRuleUpdateRequest(
    @param:Json(name = "expected_updated_at")
    val expectedUpdatedAt: String,
    val keyword: String? = null,
    val category: String? = null,
    val enabled: Boolean? = null,
    val priority: Int? = null,
    @param:Json(name = "amount_min_cents")
    val amountMinCents: Long? = null,
    @param:Json(name = "amount_max_cents")
    val amountMaxCents: Long? = null,
    @param:Json(name = "source_contains")
    val sourceContains: String? = null,
    @param:Json(name = "tag_contains")
    val tagContains: String? = null,
)

/**
 * ADR-0038 PR-1: DELETE /api/rules/categories/{id} carries a body so
 * the optimistic-concurrency token travels through the same channel as
 * PATCH. Mirrors backend ``CategoryRuleDeleteRequest``.
 */
data class CategoryRuleDeleteRequest(
    @param:Json(name = "expected_updated_at")
    val expectedUpdatedAt: String,
)

data class RuleApplicationBatchDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val status: String,
    @param:Json(name = "pending_scanned")
    val pendingScanned: Int,
    @param:Json(name = "changed_count")
    val changedCount: Int,
    @param:Json(name = "created_at")
    val createdAt: String,
    @param:Json(name = "rolled_back_at")
    val rolledBackAt: String? = null,
)

data class RuleApplicationListDto(
    val items: List<RuleApplicationBatchDto>,
)

data class RuleApplicationRollbackDto(
    @param:Json(name = "public_id")
    val publicId: String,
    val status: String,
    val changed: Int,
    val skipped: Int,
    @param:Json(name = "rolled_back_at")
    val rolledBackAt: String? = null,
)

data class RuleApplyConfirmedRequestDto(
    val confirm: Boolean = false,
    @param:Json(name = "preview_token")
    val previewToken: String? = null,
)

data class RuleApplyPreviewItemDto(
    val id: Long,
    val merchant: String?,
    @param:Json(name = "current_category")
    val currentCategory: String,
    @param:Json(name = "suggested_category")
    val suggestedCategory: String,
    @param:Json(name = "rule_keyword")
    val ruleKeyword: String,
    val reason: String,
)

data class RuleApplyConfirmedResponseDto(
    @param:Json(name = "dry_run")
    val dryRun: Boolean,
    @param:Json(name = "confirmed_scanned")
    val confirmedScanned: Int,
    @param:Json(name = "changed_count")
    val changedCount: Int,
    val items: List<RuleApplyPreviewItemDto> = emptyList(),
    @param:Json(name = "skipped_non_default_category")
    val skippedNonDefaultCategory: Int = 0,
    @param:Json(name = "no_match_count")
    val noMatchCount: Int = 0,
    @param:Json(name = "unchanged_count")
    val unchangedCount: Int = 0,
    @param:Json(name = "conflict_count")
    val conflictCount: Int = 0,
    @param:Json(name = "scan_limit_reached")
    val scanLimitReached: Boolean = false,
    @param:Json(name = "scan_limit")
    val scanLimit: Int = 0,
    @param:Json(name = "preview_token")
    val previewToken: String? = null,
)
